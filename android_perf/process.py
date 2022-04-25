from abc import ABCMeta
import re

from .abstract_adb import AdbInterface


class ProcessAdb(AdbInterface, metaclass=ABCMeta):
    def find_processes(self, app_bundle: str) -> list:
        """
        每个app可能会有多个进程
        :param app_bundle: 包名
        :return: list: [(进程ID，父进程ID，进程名)]
        """
        rs = self.run_shell(f'ps -A | grep {app_bundle}')
        ll = []
        for x in rs.split('\n'):
            d = re.split(r'\s+', x)
            if not d or not d[0]:
                continue
            ll.append((d[1], d[2], d[-1]))
        return ll

    def find_process_ids(self, app_bundle: str) -> list:
        return [p[0] for p in self.find_processes(app_bundle)]

    def find_main_process_id(self, app_bundle: str) -> str:
        for p in self.find_processes(app_bundle):
            if p[-1].find(':') == -1:
                return p[0]
        raise ValueError('No Process Found!')
