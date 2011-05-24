from OpenGL import GL
from EMAN2 import Transform
from libpyGLUtils2 import GLUtil


class EMItem3D(object): #inherit object for new-style class (new-stype classes required for super() and Python properties)
	"""
	The base class for nodes in our scene graph, which is used in our 3D scene viewer.
	In our case, the scene graph is a tree data structure.
	"""
	# Class attrib to connect openGL int identifiers to class instances
	selection_idx_dict = {}
	
	def __init__(self, intname, parent = None, children = set(), transform = None):
		"""
		@type parent: EMItem3D
		@param parent: the parent node to the current node or None for the root node
		@type children: set type (list or tuple will be converted to a set)
		@param children: the child nodes
		@type transform: Transform or None
		@param transform: The transformation (rotation, scaling, translation) that should be applied before rendering this node and its children 
		"""
		#NOTE: Accessor methods are not needed; Python "properties" can be used instead if needed.
		self.parent = parent		
		self.children = set(children)
		self.transform = transform
		self.is_visible = True 
		self.is_selected = False
		self.intname = intname
	
	def add_child(self, node):
		"""
		Adds a child node, if not already in the set of child nodes.
		@type node: EMItem3D
		@param node: the child node to add
		"""
		self.children.add(node)
		node.parent = self
			
	def has_child(self, node):
		"""
		Tests whether the supplied node is a child of the current node. 
		@type node: EMItem3D
		@param node: test whether this node is a child node of self 
		"""
		return node in self.children
		
	def remove_child(self, node):
		"""
		Remove the supplied node from the set of child nodes. 
		@type node: EMItem3D
		@param node: the node to remove
		"""
		self.children.remove(node)
		node.parent = None
		
	def get_all_selected_nodes(self): #TODO: test!
		"""
		For the tree rooted at self, this recursive method returns a list of all the selected nodes.
		@return: a list of selected nodes
		"""
		selected_list = []
		if self.is_selected:
			selected_list.append(self)
		for child in self.children: #Recursion ends on leaf nodes here
			selected_list.extend(child.get_all_selected_nodes()) #Recursion
		
		return selected_list
	
	def get_nearest_selected_nodes(self): #TODO: test!
		"""
		For the tree rooted at self, this recursive method returns a list of the selected nodes that are nearest to self.
		A selected node will not be in the returned list if one of its ancestor nodes is also selected. 
		@return: a list of selected nodes
		"""
		selected_list = []
		if self.is_selected:
			return [self]
		else:
			for child in self.children:
				selected_list.extend(child.get_nearest_selected_nodes())
		
		return selected_list
	
	def get_farthest_selected_nodes(self): #TODO: test!
		"""
		For the tree rooted at self, this recursive method returns a list of the selected nodes that are farthest from self.
		A selected node will not be in the returned list if one of its descendant nodes is also selected. 
		@return: a list of selected nodes
		"""
		selected_list = []
		for child in self.children:
			selected_list.extend(child.get_farthest_selected_nodes())
		if not selected_list: #either this is a leaf node, or there are no selected nodes in the child subtrees
			if self.is_selected:
				selected_list.append(self)
		
		return selected_list

	def update_matrices(self, params, xformtype):
		"""
		@type params: List
		@param params: A list defining how the transform in each active node is modified
		@type xfromtype: sting
		@param xformtype: The sort of transform we wish to do
		"""
		if self.is_selected:
			if xformtype == "rotate":
				self.transform.rotate_origin(Transform({"type":"spin","Omega":params[0],"n1":params[1],"n2":params[2],"n3":params[3]}))
			elif xformtype == "translate":
				self.transform.translate(params[0], params[1], params[2])
			elif xformtype == "scale":
				self.transform.scale(params[0])
			else:
				raise Exception,"Invalid transformation type"
		
		# Now tell all children to update
		for child in self.children:
			child.update_matrices(params, xformtype)
			
	def render(self, selectionmode=False):
		"""
		This is the method to call to render the node and its child nodes. 
		It calls self.render_node() to render the current node. 
		Usually, this method is unchanged in subclasses. 
		"""
		if not self.is_visible:
			return #Also applies to subtree rooted at this node
		
		if selectionmode: GL.glPushName(self.intname)
		if self.transform != None:
			GL.glPushMatrix()
			GLUtil.glMultMatrix(self.transform) #apply the transformation
			
			self.render_node()
			for child in self.children:
				child.render(selectionmode)
		
			GL.glPopMatrix()
			
		else:
			self.render_node()
			for child in self.children:
				child.render(selectionmode)
		if selectionmode: GL.glPopName()

	def render_node(self):
		"""
		This method, which is called by self.render(), renders the current node.
		It should be implemented in subclasses that represent visible objects.
		"""
		pass

	def keyPressEvent(self, event): pass
	def keyReleaseEvent(self, event): pass
	def mouseDoubleClickEvent(self, event): pass
	def mouseMoveEvent(self, event): pass
	def mousePressEvent(self, event): pass
	def mouseReleaseEvent(self, event): pass
	def wheelEvent(self, event): pass