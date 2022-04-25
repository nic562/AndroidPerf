from abc import ABCMeta
import re
import time

from .abstract_adb import AdbInterface
from .log import default as logging


class SurfaceAdb(AdbInterface, metaclass=ABCMeta):

    def get_focus_activity(self) -> str:
        """
        通过dumpsys window windows获取activity名称
        """
        activity_name = ''
        activity_line = ''
        for line in self.run_shell('dumpsys window windows').split('\n'):
            if line.find('mCurrentFocus') != -1:
                activity_line = line.strip()
        if activity_line:
            activity_line_split = activity_line.split(' ')
        else:
            return activity_name
        if len(activity_line_split) > 1:
            if activity_line_split[1] == 'u0':
                activity_name = activity_line_split[2].rstrip('}')
            else:
                activity_name = activity_line_split[1]
        return activity_name

    def clear_surfaceflinger(self, win_name: str = ''):
        return self.run_shell(f'dumpsys SurfaceFlinger --latency-clear {win_name}')

    def get_surfaceflinger_details_by_window(self, win_name: str):
        return self.run_shell(f'dumpsys SurfaceFlinger --latency {win_name}')

    def get_surfaceflinger_details_by_bundle(self, bundle: str):
        return self.run_shell(f'dumpsys gfxinfo {bundle} framestats')




