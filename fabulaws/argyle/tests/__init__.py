import os

from .utils import unittest

def main():
    suite = unittest.loader.defaultTestLoader.discover(os.path.dirname(__file__))
    unittest.TextTestRunner(verbosity=2).run(suite)
