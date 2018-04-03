import copy
import random
import urllib2

from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import uses_fabric
from fabulaws.ubuntu.packages.base import AptMixin


class PythonMixin(AptMixin):
    """
    FabulAWS Ubuntu mixin that installs Python
    """

    package_name = 'python'
    python_ppa = None
    python_packages = ['python', 'python-dev']
    python_install_tools = True
    python_pip_version = None # install the latest version
    python_virtualenv_version = None # install the latest version

    @uses_fabric
    def install_python_tools(self):
        """
        Installs the required Python tools from PyPI.
        """

        mirror = 'https://pypi.python.org'
        version = ''
        if self.python_pip_version:
            version = '==%s' % self.python_pip_version
        sudo("easy_install -i %s/simple/ -U pip%s" % (mirror, version))
        version = ''
        if self.python_virtualenv_version:
            version = '==%s' % self.python_virtualenv_version
        sudo("pip install -i %s/simple/ -U virtualenv%s" % (mirror, version))

    def setup(self):
        """
        Hook into the FabulAWS setup() routine to install Python and related
        tools.
        """
        super(PythonMixin, self).setup()
        if self.python_install_tools:
            self.install_packages(['python-setuptools'])
            self.install_python_tools()
