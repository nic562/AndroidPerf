# coding=utf8


class AppInfo(object):
    name = None
    alias = None
    pkg = None
    platform = None
    version = None
    description = None
    run_args = None

    def __init__(self, info_json: dict = None):
        if info_json:
            self._load_by_json(info_json)

    @classmethod
    def simple(cls, name, pkg, **kv):
        o = cls()
        o.name = name
        o.pkg = pkg
        for k, v in kv.items():
            setattr(o, k, v)
        return o

    def _load_by_json(self, json: dict):
        raise NotImplementedError

    def __str__(self):
        return f'{self.alias} {self.platform} {self.pkg} v:{self.version or "-"}'
