
import abc
import types


class AdbInterface(metaclass=abc.ABCMeta):
    # 基础ADB通讯接口抽象
    _sdk_version: int

    @abc.abstractmethod
    def run_shell(self, cmd: str, clean_wrap=False) -> str:
        """
        执行命令
        :param cmd: 命令内容
        :param clean_wrap: 是否清理结果换行 (\\r)
        :return:
        """
        raise NotImplementedError

    @abc.abstractmethod
    def stream_shell(self, cmd: str) -> types.GeneratorType:
        """
        执行命令，返回输出流的迭代器，每次返回一行输出结果
        :param cmd: 命令内容
        :return: 每行输出结果迭代
        """
        raise NotImplementedError

    @abc.abstractmethod
    def close(self):
        raise NotImplementedError

    @abc.abstractmethod
    def install_app(self, apk_path):
        raise NotImplementedError

    @abc.abstractmethod
    def uninstall_app(self, app_bundle: str):
        raise NotImplementedError

    @abc.abstractmethod
    def push_file(self, local_path: str, device_path: str):
        raise NotImplementedError

    @abc.abstractmethod
    def pull_file(self, device_path: str, local_path: str):
        raise NotImplementedError

    @abc.abstractmethod
    def get_device_serial(self) -> str:
        raise NotImplementedError

    def get_sdk_version(self) -> int:
        if not self._sdk_version:
            self._sdk_version = int(self.run_shell('getprop ro.build.version.sdk'))
        return self._sdk_version

