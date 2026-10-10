from glob import glob
from setuptools import find_packages, setup


package_name = "asr_ros2"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml", "README.md"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="ASR Runtime",
    maintainer_email="support@asr.example",
    description="ROS 2 host-side connection diagnostics and sensor monitoring for ASR Runtime.",
    license="Proprietary",
    entry_points={
        "console_scripts": [
            "asr_link_manager = asr_ros2.asr_link_manager:main",
        ],
    },
)
