from PySide6.QtWidgets import QSizePolicy

MAX_TASK_INFO_TABLE_HEIGHT = 300


def calculate_task_info_table_height(
    header_height,
    row_heights,
    frame_width=0,
    scroll_bar_height=0,
    max_height=MAX_TASK_INFO_TABLE_HEIGHT,
):
    content_height = (
        max(0, header_height)
        + sum(max(0, height) for height in row_heights)
        + max(0, frame_width) * 2
        + max(0, scroll_bar_height)
    )
    if max_height <= 0:
        return content_height
    return min(content_height, max_height)


def update_task_info_table_height(task_tab):
    """[lw] Keep the framework task info card at its content height."""
    table = getattr(task_tab, "task_info_table", None)
    if table is None:
        return

    scroll_bar = table.horizontalScrollBar()
    scroll_bar_height = scroll_bar.height() if scroll_bar.isVisible() else 0
    height = calculate_task_info_table_height(
        table.horizontalHeader().height(),
        [table.rowHeight(row) for row in range(table.rowCount())],
        frame_width=table.frameWidth(),
        scroll_bar_height=scroll_bar_height,
    )
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    table.setFixedHeight(height)
    table.updateGeometry()

    container = getattr(task_tab, "task_info_container", None)
    if container is not None:
        # Task cards use an expanding vertical policy. Without fixing this outer
        # container, QVBoxLayout gives all spare height to the transparent part
        # below the visible info card and pushes task cards to the page bottom.
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        container.updateGeometry()


def install_task_info_layout(main_window):
    """[lw] Apply the adaptive height adapter to framework-created task tabs."""
    task_tabs = [
        getattr(main_window, "trigger_tab", None),
        getattr(main_window, "onetime_tab", None),
        *getattr(main_window, "grouped_task_tabs", []),
    ]
    for task_tab in task_tabs:
        if task_tab is None or getattr(task_tab, "_lw_task_info_layout_callback", None):
            continue

        def update_height(tab=task_tab):
            update_task_info_table_height(tab)

        task_tab._lw_task_info_layout_callback = update_height
        task_tab.timer.timeout.connect(update_height)
        update_height()
