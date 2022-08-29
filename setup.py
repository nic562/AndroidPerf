from setuptools import setup

from android_perf import __version__


def parse_requirements(filename):
    """ load requirements from a pip requirements file. (replacing from pip.req import parse_requirements)"""
    content = (line.strip() for line in open(filename))
    return [line for line in content if line and not line.startswith("#")]


setup(
    name='AndroidPerf',
    packages=['android_perf'],
    version=__version__,
    author='Nicholas Chen',
    author_email='nic562@gmail.com',
    license='Apache License 2.0',
    url='https://github.com/nic562/AndroidPerf',
    description='基于python-adb、pure-python-adb等采集性能',
    keywords=['android', 'adb', 'pure-python-adb'],
    install_requires=parse_requirements('requirements.txt'),
    classifiers=[
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
    ],
)
