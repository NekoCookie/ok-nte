"""全链路断裂扫描: 对比 merge-base(46e9225) 与当前代码的上游符号差异,
再对照用户代码(src/lw/ + 用户全权文件 + 上游文件中的[lw]行)的全部引用, 一次找全。

视角A: 上游"消失的符号"(方法/类属性/模块级名/self.实例字段) ∩ 用户代码引用 → 断裂
视角B: 用户代码引用的属性名, 在当前(上游文件+ok库)的定义/赋值全集中找不到 → 可疑
视角C: 同名方法在新旧两版签名(参数)或返回形态(元组vs单值)变了, 且用户代码引用过 → 需人工过
"""
import ast
import glob
import os
import subprocess
import sys

MB = "46e9225"
# 用户全权文件(upstream/main 里不存在的本地文件 + src/lw)
USER_FILES = set()
upstream_files = set(
    subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "upstream/main", "src"],
        capture_output=True, text=True, encoding="utf-8",
    ).stdout.split()
)
for f in glob.glob("src/**/*.py", recursive=True):
    f = f.replace("\\", "/")
    if f not in upstream_files:
        USER_FILES.add(f)

UPSTREAM_LOCAL = sorted(
    f.replace("\\", "/") for f in glob.glob("src/**/*.py", recursive=True)
    if f.replace("\\", "/") not in USER_FILES
)


def parse(src):
    try:
        return ast.parse(src)
    except SyntaxError:
        return None


def collect_defs(tree):
    """返回 (names, methods, self_attrs, func_sigs)
    names: 模块级函数/类/常量名 + 类方法/类属性名 的并集
    func_sigs: {方法名: (参数名元组, 是否return元组)}"""
    names, self_attrs, sigs = set(), set(), {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            args = tuple(a.arg for a in node.args.args)
            ret_tuple = any(
                isinstance(r.value, ast.Tuple)
                for r in ast.walk(node)
                if isinstance(r, ast.Return) and r.value is not None
            )
            sigs[node.name] = (args, ret_tuple)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for tg in stmt.targets:
                        if isinstance(tg, ast.Name):
                            names.add(tg.id)
                elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    names.add(stmt.target.id)
        elif isinstance(node, ast.Assign):
            for tg in node.targets:
                if isinstance(tg, ast.Name):
                    names.add(tg.id)
                for sub in ast.walk(tg):
                    if (
                        isinstance(sub, ast.Attribute)
                        and isinstance(sub.value, ast.Name)
                        and sub.value.id == "self"
                    ):
                        self_attrs.add(sub.attr)
        elif isinstance(node, ast.AnnAssign):
            tg = node.target
            if isinstance(tg, ast.Name):
                names.add(tg.id)
            elif (
                isinstance(tg, ast.Attribute)
                and isinstance(tg.value, ast.Name)
                and tg.value.id == "self"
            ):
                self_attrs.add(tg.attr)
    return names, self_attrs, sigs


def git_show(rev, path):
    r = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, text=True, encoding="utf-8")
    return r.stdout if r.returncode == 0 else None


# ---- 旧版(merge-base)上游符号全集 ----
old_files = [
    f for f in subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", MB, "src"],
        capture_output=True, text=True, encoding="utf-8",
    ).stdout.split()
    if f.endswith(".py")
]
old_names, old_self, old_sigs = set(), set(), {}
for f in old_files:
    src = git_show(MB, f)
    tree = parse(src) if src else None
    if tree:
        n, s, g = collect_defs(tree)
        old_names |= n
        old_self |= s
        for k, v in g.items():
            old_sigs.setdefault(k, v)

# ---- 当前上游文件 + ok 库 符号全集 ----
new_names, new_self, new_sigs = set(), set(), {}
ok_dir = None
try:
    import ok as _ok
    ok_dir = os.path.dirname(_ok.__file__)
except Exception:
    pass
scan_now = list(UPSTREAM_LOCAL)
if ok_dir:
    scan_now += glob.glob(os.path.join(ok_dir, "**", "*.py"), recursive=True)
for f in scan_now:
    try:
        tree = parse(open(f, encoding="utf-8").read())
    except OSError:
        continue
    if tree:
        n, s, g = collect_defs(tree)
        new_names |= n
        new_self |= s
        for k, v in g.items():
            new_sigs.setdefault(k, v)

removed_names = (old_names | old_self) - (new_names | new_self)

# ---- 引用侧: 用户文件全部属性/名字引用; 上游文件的[lw]行文本 ----
usage = {}  # name -> [位置...]
for f in sorted(USER_FILES):
    try:
        src = open(f, encoding="utf-8").read()
    except OSError:
        continue
    tree = parse(src)
    if not tree:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            usage.setdefault(node.attr, []).append(f"{f}:{node.lineno}")

lw_lines = []  # 上游文件中的 [lw] 行: (file, lineno, text)
for f in UPSTREAM_LOCAL:
    try:
        for i, line in enumerate(open(f, encoding="utf-8"), 1):
            if "[lw]" in line:
                lw_lines.append((f, i, line.strip()))
    except OSError:
        pass

print("=== A. 用户代码引用了上游已删除的符号 ===")
hits = sorted(set(usage) & removed_names)
for name in hits:
    locs = usage[name][:4]
    print(f"  {name}: {', '.join(locs)}")
if not hits:
    print("  (无)")

print("\n=== A2. 上游文件[lw]行中引用了已删除符号 ===")
found = False
for f, i, text in lw_lines:
    for name in removed_names:
        if len(name) > 4 and name in text:
            print(f"  {f}:{i}: {name}  | {text[:90]}")
            found = True
if not found:
    print("  (无)")

print("\n=== B. 用户代码引用的属性在当前上游+ok库定义/赋值全集中找不到 ===")
known_now = new_names | new_self
# 用户文件之间互相定义的符号也算已知(lw 自己的方法/字段), 但仅统计 def/类属性,
# 不把"用户文件里的 self.X 赋值"直接当已知(那是上次洗白 skip_sleep_check 的漏洞)——
# 改为: 用户文件的 def/类属性算已知; 用户文件 self.X 赋值单独收集, 命中时标注[自赋值]提示人工看。
user_defs, user_self = set(), set()
for f in USER_FILES:
    try:
        tree = parse(open(f, encoding="utf-8").read())
    except OSError:
        continue
    if tree:
        n, s, _ = collect_defs(tree)
        user_defs |= n
        user_self |= s
missing = []
for name, locs in sorted(usage.items()):
    if name.startswith("__"):
        continue
    if name in known_now or name in user_defs:
        continue
    tag = " [仅用户侧自赋值]" if name in user_self else ""
    missing.append(f"  {name}{tag}: {', '.join(locs[:3])}")
print("\n".join(missing) if missing else "  (无)")

print("\n=== C. 用户代码引用过、且新旧签名/返回形态变了的方法 ===")
for name in sorted(set(usage) & set(old_sigs) & set(new_sigs)):
    if old_sigs[name] != new_sigs[name]:
        oa, ot = old_sigs[name]
        na, nt = new_sigs[name]
        diffs = []
        if oa != na:
            diffs.append(f"参数 {oa} -> {na}")
        if ot != nt:
            diffs.append(f"return元组 {ot} -> {nt}")
        print(f"  {name}: {'; '.join(diffs)}  (引用: {usage[name][0]})")
