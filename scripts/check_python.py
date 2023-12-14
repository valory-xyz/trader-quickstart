import sys

if (
    sys.version_info.major != 3
    or sys.version_info.minor < 8
    or sys.version_info.minor > 11
):
    print(
        "Python version >=3.8.0, <3.12.0 is required but found "
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    sys.exit(1)

print(
    "Python version "
    f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    " is compatible\n"
)
