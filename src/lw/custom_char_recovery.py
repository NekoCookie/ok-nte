"""Recover LW implementation assignments lost by an early v7 migration."""

import json
from pathlib import Path


_REPAIR_KEY = "restore_legacy_template_impl_ids"
_REPAIR_STATE_KEY = "lw_repairs"
_LW_LEGACY_IMPL_IDS = {
    "char_requiem": "builtin:requiem",
    "template_main_dps": "builtin:template_main_dps",
    "template_buff_support": "builtin:template_buff_support",
    "template_heal_support": "builtin:template_heal_support",
    "template_sakiri_buff_support": "builtin:template_sakiri_buff_support",
}


def restore_legacy_template_impl_ids(data: dict, backup_path: str) -> list[str]:
    """Restore only blank LW impl IDs from the pre-v7 backup, once per database."""

    if not isinstance(data, dict):
        return []

    repair_state = data.get(_REPAIR_STATE_KEY)
    if isinstance(repair_state, dict) and repair_state.get(_REPAIR_KEY):
        return []

    try:
        with Path(backup_path).open(encoding="utf-8") as file:
            backup = json.load(file)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(backup, dict):
        return []
    try:
        source_schema_version = int(backup.get("schema_version", 0))
    except (TypeError, ValueError):
        return []
    if source_schema_version >= 7:
        return []

    characters = data.get("characters")
    backup_characters = backup.get("characters")
    if not isinstance(characters, dict) or not isinstance(backup_characters, dict):
        return []

    restored_names = []
    for char_id, record in characters.items():
        previous = backup_characters.get(char_id)
        if not isinstance(record, dict) or not isinstance(previous, dict):
            continue
        if str(record.get("impl_id", "") or "").strip():
            continue
        if str(record.get("name", "") or "").strip() != str(previous.get("name", "") or "").strip():
            continue

        legacy_impl_id = str(previous.get("combo_id", "") or "").strip()
        restored_impl_id = _LW_LEGACY_IMPL_IDS.get(legacy_impl_id)
        if not restored_impl_id:
            continue
        record["impl_id"] = restored_impl_id
        restored_names.append(str(record.get("name", char_id)))

    if restored_names:
        repair_state = repair_state if isinstance(repair_state, dict) else {}
        repair_state[_REPAIR_KEY] = True
        data[_REPAIR_STATE_KEY] = repair_state

    return restored_names
