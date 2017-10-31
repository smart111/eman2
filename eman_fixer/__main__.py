#!/usr/bin/env python

import sys, os
# from lib2to3.main import main
# # from eman_fixer.fix_eman_div import FixEmanFixer
# 
# sys.path.append(os.path.pardir(os.path.abspath(__file__))
# sys.exit(main('FixEmanFixer'))
# sys.exit(main())


# import sys
from lib2to3.main import main

sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
print sys.path
sys.exit(main("fix_eman_div"))


# import argparse
# # from fix_eman_div import FixEmanFixer
# import sys
# from StringIO import StringIO
# 
# # Local imports
# from lib2to3 import pytree
# from lib2to3.pgen2 import driver
# from lib2to3.pygram import python_symbols, python_grammar
# 
# driver = driver.Driver(python_grammar, convert=pytree.convert)
# 
# 
# def main():
#     # usage = "find_pattern.py [options] [string]"
#     parser = argparse.ArgumentParser()
#     parser.add_argument("file")
# 
#     # Parse command line arguments
#     args = parser.parse_args()
#     
#     # fixer = FixEmanFixer(None, None)
# 
#     tree = driver.parse_file(args.file)
#     
#     # print tree
# 
# 
#     examine_tree(tree)
# 
# def examine_tree(tree):
#     for node in tree.post_order():
#         # if isinstance(node, pytree.Leaf):
#         #     continue
#         # print repr(str(node))
#         # verdict = raw_input()
#         print type(node), node
# 
# 
# if __name__ == '__main__':
#     main()