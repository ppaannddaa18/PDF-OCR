"""
撤销/重做命令模式实现
"""
from abc import ABC, abstractmethod
from typing import List, Callable, Optional
from copy import deepcopy
from app.models.region import Region


class Command(ABC):
    """命令基类"""
    @abstractmethod
    def execute(self):
        pass

    @abstractmethod
    def undo(self):
        pass

    @abstractmethod
    def redo(self):
        pass


class AddRegionCommand(Command):
    """添加区域命令"""
    def __init__(self, region: Region, add_callback: Callable, remove_callback: Callable):
        self.region = deepcopy(region)  # 深拷贝
        self.add_callback = add_callback
        self.remove_callback = remove_callback

    def execute(self):
        self.add_callback(self.region)

    def undo(self):
        self.remove_callback(self.region.id)

    def redo(self):
        self.execute()


class RemoveRegionCommand(Command):
    """删除区域命令"""
    def __init__(self, region: Region, remove_callback: Callable, add_callback: Callable):
        self.region = deepcopy(region)  # 深拷贝
        self.remove_callback = remove_callback
        self.add_callback = add_callback

    def execute(self):
        self.remove_callback(self.region.id)

    def undo(self):
        self.add_callback(self.region)

    def redo(self):
        self.execute()


class UpdateRegionCommand(Command):
    """更新区域命令（移动或调整大小）"""
    def __init__(self, region_id: str, old_region: Region, new_region: Region,
                 update_callback: Callable):
        self.region_id = region_id
        self.old_region = deepcopy(old_region)  # 深拷贝
        self.new_region = deepcopy(new_region)  # 深拷贝
        self.update_callback = update_callback

    def execute(self):
        self.update_callback(self.new_region)

    def undo(self):
        self.update_callback(self.old_region)

    def redo(self):
        self.execute()


class UpdateFieldNameCommand(Command):
    """更新字段名命令"""
    def __init__(self, region_id: str, old_name: str, new_name: str,
                 update_callback: Callable):
        self.region_id = region_id
        self.old_name = old_name
        self.new_name = new_name
        self.update_callback = update_callback

    def execute(self):
        self.update_callback(self.region_id, self.new_name)

    def undo(self):
        self.update_callback(self.region_id, self.old_name)

    def redo(self):
        self.execute()


class ClearAllCommand(Command):
    """清空所有区域命令"""
    def __init__(self, regions: List[Region], clear_callback: Callable,
                 restore_callback: Callable):
        self.regions = [deepcopy(r) for r in regions]  # 深拷贝所有区域
        self.clear_callback = clear_callback
        self.restore_callback = restore_callback

    def execute(self):
        self.clear_callback()

    def undo(self):
        self.restore_callback(self.regions)

    def redo(self):
        self.execute()


class CommandHistory:
    """命令历史管理器"""
    def __init__(self, max_size: int = 20):
        self.commands: List[Command] = []
        self.current_index = -1
        self.max_size = max_size

    def execute(self, command: Command):
        """执行新命令"""
        # 如果当前不在历史末尾，删除后面的命令
        if self.current_index < len(self.commands) - 1:
            self.commands = self.commands[:self.current_index + 1]

        command.execute()
        self.commands.append(command)
        self.current_index += 1

        # 限制历史大小
        if len(self.commands) > self.max_size:
            self.commands.pop(0)
            self.current_index -= 1

    def can_undo(self) -> bool:
        return self.current_index >= 0

    def can_redo(self) -> bool:
        return self.current_index < len(self.commands) - 1

    def undo(self) -> bool:
        """撤销上一步操作"""
        if not self.can_undo():
            return False
        command = self.commands[self.current_index]
        command.undo()
        self.current_index -= 1
        return True

    def redo(self) -> bool:
        """重做下一步操作"""
        if not self.can_redo():
            return False
        self.current_index += 1
        command = self.commands[self.current_index]
        command.redo()
        return True

    def clear(self):
        """清空历史"""
        self.commands.clear()
        self.current_index = -1
