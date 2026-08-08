"""Setup script for NFC URL Writer."""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="nfc-url-writer",
    version="1.0.0",
    author="NFC URL Writer Contributors",
    description="Cross-platform desktop app for writing URLs to NFC tags using ACR122U reader",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/NFC_URL_Writer_pyapp",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
    ],
    python_requires=">=3.10",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "nfc-url-writer=nfc_url_writer.main:main",
        ],
    },
)

