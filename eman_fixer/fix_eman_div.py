from lib2to3.fixer_base import BaseFix
from lib2to3.pgen2 import token


class FixEmanDiv(BaseFix):
    
    # def __init__(self):
    #     print __name__

    # _accept_type = token.NAME
    
    def match(self, node):
        print node
        print "==="*50
        # if node.value == 'oldname':
        #     return True
        # return False
        return True

    def transform(self, node, results):
        # node.value = 'newname'
        # node.changed()
        print node, results
        
