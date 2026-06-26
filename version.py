"""앱 버전 단일 출처.

PyInstaller 번들에 frozen되며, CI에서 git 태그를 기반으로 installer.iss에도
동일한 버전 문자열(/DAppVersion=)을 전달한다.
버전을 올릴 때는 이 파일만 수정하면 된다.
"""
__version__ = "1.0.12"
