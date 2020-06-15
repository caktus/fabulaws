
from .utils import unittest, ArgyleTest
from argyle import npm


class NPMTest(ArgyleTest):
    "Base for setting up necessary patches."

    package = 'argyle.npm'
    patched_commands = ['sudo', ]


class NPMCommandsTest(NPMTest):
    "Common NPM commands for installing and updating packages."

    def test_install_package(self):
        "Install a new package."
        npm.npm_install('less')
        self.assertSudoCommand('npm install less')

    def test_install_package_globally(self):
        "Install a new package with the global flag."
        npm.npm_install('less', flags='--global')
        self.assertSudoCommand('npm install less --global')

    def test_update_package(self):
        "Update a package."
        npm.npm_update('less')
        self.assertSudoCommand('npm update less')

    def test_remove_package(self):
        "Uninstall a package."
        npm.npm_uninstall('less')
        self.assertSudoCommand('npm uninstall less')


if __name__ == '__main__':
    unittest.main()
