"""Package the workstation client for installation from the library server."""

from importlib.resources import files
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile


DOWNLOAD_ROUTE = "/api/client/download"
FILENAME = "paper-client.zip"
SOURCES = ("pyproject.toml", "__init__.py", "__main__.py", "agent.py", "artifacts.py", "paper_source.py", "review.py", "ssh_key.py")


def archive():
    package = files("paper_client")
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as bundle:
        for name in SOURCES:
            bundle.writestr(f"paper-client/{name}", package.joinpath(name).read_bytes())
    return output.getvalue()
