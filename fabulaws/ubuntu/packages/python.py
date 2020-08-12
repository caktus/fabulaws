from fabric.api import sudo

from fabulaws.decorators import uses_fabric
from fabulaws.ubuntu.packages.base import AptMixin


class PythonMixin(AptMixin):
    """
    FabulAWS Ubuntu mixin that installs Python
    """

    package_name = "python"
    python_ppa = None
    python_packages = ["python3", "python3-dev"]
    python_install_tools = True
    python_virtualenv_version = None  # install the latest version

    @uses_fabric
    def install_python_tools(self):
        """
        Installs the required Python tools from PyPI.
        """

        sudo("curl https://bootstrap.pypa.io/get-pip.py --output /tmp/get-pip.py")
        sudo("python3 /tmp/get-pip.py")
        version = ""
        if self.python_virtualenv_version:
            version = "==%s" % self.python_virtualenv_version
        sudo("pip install -U virtualenv%s" % version)

    def setup(self):
        """
        Hook into the FabulAWS setup() routine to install Python and related
        tools.
        """
        super(PythonMixin, self).setup()
        if self.python_install_tools:
            self.install_python_tools()
