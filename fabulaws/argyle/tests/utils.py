"Test helper utility methods."

try:
    import unittest2 as unittest
except ImportError:
    import unittest

from mock import patch


class ArgyleTest(unittest.TestCase):
    "Common test base."

    package = ''
    patched_commands = []

    def setUp(self):
        "Setup patches for Fabric commands."
        self.patches = {}
        self.mocks = {}
        for command in self.patched_commands:
            self.patches[command] = patch('%s.%s' % (self.package, command))
            self.mocks[command] = self.patches[command].start()            

        
    def tearDown(self):
        "Remove patched commands."
        for command, patched in self.patches.items():
            patched.stop()

    def _assertCommand(self, fabric_command, expected, called=True):
        "Search the Fabric command calls for a given command."
        mocked = self.mocks[fabric_command]
        self.assertTrue(mocked.called, "%s was never called." % fabric_command)
        commands = []
        for args, kwargs in mocked.call_args_list:
            commands.append(args[0])
        found = any([command == expected for command in commands])
        if called:
            msg = "%s not found in %s" % (expected, commands)
            self.assertTrue(found, msg)
        else:
            msg = "%s was found in %s" % (expected, commands)
            self.assertFalse(found, msg)

    def assertSudoCommand(self, expected):
        "Assert sudo was called with a particular command."
        self._assertCommand('sudo', expected)

    def assertNoSudoCommand(self, expected):
        "Assert sudo was never called with a particular command."
        self._assertCommand('sudo', expected, called=False)

    def assertRunCommand(self, expected):
        "Assert run was called with a particular command."
        self._assertCommand('run', expected)

    def assertNoRunCommand(self, expected):
        "Assert run was never called with a particular command."
        self._assertCommand('run', expected, called=False)

    def assertTemplateUsed(self, expected):
        "Assert tempate used in an upload_template call."
        upload_template = self.mocks['upload_template']
        self.assertTrue(upload_template.called, "upload_template was never called.")
        args, kwargs = upload_template.call_args
        template_name = args[0]
        self.assertEqual(template_name, expected)

    def assertTemplateDesination(self, expected):
        "Assert location for uploaded template."
        upload_template = self.mocks['upload_template']
        self.assertTrue(upload_template.called, "upload_template was never called.")
        args, kwargs = upload_template.call_args
        destination = args[1]
        self.assertEqual(destination, expected)

    def assertTemplateContext(self, expected):
        "Assert addition context passed to an uploaded template."
        upload_template = self.mocks['upload_template']
        self.assertTrue(upload_template.called, "upload_template was never called.")
        args, kwargs = upload_template.call_args
        context = kwargs['context']
        self.assertEqual(context, expected)
