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
    python_pypi_mirrors = [
        'http://pypi.python.org',
        #'http://b.pypi.python.org', # as of 1/5/12, doesn't have virtualenv==1.7
        'http://c.pypi.python.org',
        'http://d.pypi.python.org',
        'http://e.pypi.python.org',
        'http://f.pypi.python.org',
    ]

    def _find_mirror(self):
        """
        Finds a PyPI mirror that appears to be online.
        """

        for mirror in self.python_pypi_mirrors:
            try:
                r = urllib2.urlopen(mirror)
                if r.code == 200:
                    return mirror
            except urllib2.URLError:
                pass
        raise ValueError('No active mirror found.')

    @uses_fabric
    def install_python_tools(self):
        """
        Installs the required Python tools from a random (hopefully online)
        PyPI mirror.
        """

        mirror = self._find_mirror()
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
