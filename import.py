#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

# Spread3D BlendUp import script

import os
import struct
import bpy
import json
import math
from bpy_extras.io_utils import unpack_list
import mathutils
import re
import codecs
from bpy.props import *

class BlendUpMessageOperator(bpy.types.Operator):
    bl_idname = "blenduperror.message"
    bl_label = "BLENDUP ERROR:"
    message = StringProperty()

    def execute(self, context):
        self.report({'ERROR'}, self.message)
        return {'FINISHED'}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

bpy.utils.register_class(BlendUpMessageOperator)

blenderVersion = bpy.app.version[0]*1000+bpy.app.version[1]*10+bpy.app.version[2]

if blenderVersion < 2740 :
    buperror = "Update Blender with version 2.74 or above"
    bpy.ops.blenduperror.message('INVOKE_DEFAULT', message = buperror)
    raise Exception(buperror)

class Skp2Blend:

    def __init__ ( self ):

        self.scene = bpy.context.scene

    def end( self ):

        self.scene.update()

    def matrixLookat(self, eye, target, up):
        z = eye - target
        x = up.cross(z)
        y = z.cross(x)

        x.normalize()
        y.normalize()
        z.normalize()

        rot = mathutils.Matrix()
        rot[0][0] = x[0]
        rot[0][1] = y[0]
        rot[0][2] = z[0]
        rot[0][3] = 0
        rot[1][0] = x[1]
        rot[1][1] = y[1]
        rot[1][2] = z[1]
        rot[1][3] = 0
        rot[2][0] = x[2]
        rot[2][1] = y[2]
        rot[2][2] = z[2]
        rot[2][3] = 0
        tran = mathutils.Matrix.Translation(eye)
        return tran * rot

    def importJSON( self, path, sourceDir):

        self.sourceDir = sourceDir

        #load json model from file
        fileSize = os.stat(path).st_size
        file = open(path, 'rb')
        value = file.read(fileSize).decode('utf-8')
        model = json.loads(value)
        file.close()


        #read options
        options = model['options']

        self.options = options

        self.useBlenderCycles = (options['rendering'] == "Blender Cycles")

        if options["shadow"] == 1:
            sun = bpy.data.objects.get('Sun')

            if sun :
                v1 = mathutils.Vector((0,0,0))
                v2 = mathutils.Vector((-options["shadowX"],-options["shadowY"],-options["shadowZ"]))

                sun.matrix_world = self.matrixLookat(v1,v2,mathutils.Vector((0,0,1)))
            if self.useBlenderCycles == False:
                if bpy.data.lamps.get("Sun") != None:
                    bpy.data.lamps["Sun"].shadow_method='RAY_SHADOW'

        if self.useBlenderCycles == False:
            bpy.data.worlds["World"].light_settings.use_environment_light =True

        bpy.data.scenes["Scene"].render.resolution_x = options["vpWidth"]

        bpy.data.scenes["Scene"].render.resolution_y = options["vpHeight"]



        bpy.context.scene.cycles.samples = options['samples']

        bpy.context.scene.cycles.preview_samples = options['samples']


        if self.useBlenderCycles:

            if hasattr(bpy.context.scene,"cycles") == False:
                buperror = "Please activate Cycles Render Engine addon"
                bpy.ops.blenduperror.message('INVOKE_DEFAULT', message = buperror)
                raise Exception(buperror)
            bpy.context.scene.render.engine = "CYCLES"
        else:
            bpy.context.scene.render.engine = "BLENDER_RENDER"

        #if options['useGPU'] == 0:
        #    bpy.context.user_preferences.system.compute_device_type = "NONE"
        #else:
       #     bpy.context.user_preferences.system.compute_device_type = "CUDA"

        self.pack_texture = True

        self.back_materials = ( options['back_materials'] == 1)

        self.use_sharp_edge = ( options['use_sharp_edge'] == 1)

        self.use_seam = ( options['use_seam'] == 1)

        self.use_freestyle_mark = ( options['use_freestyle_mark'] == 1)


        self.unit = options['unit']

        self.materials = {}

        self.images = {}

        self.materialGroups = {}

        #create model
        self.model = model
        self.parseModel()

        #set units

        if self.unit == "m" or self.unit == "cm" or self.unit == "mm" :
            bpy.context.scene.unit_settings.system = "METRIC"
        else:
            bpy.context.scene.unit_settings.system = "IMPERIAL"

        if self.unit == "cm":
            bpy.context.scene.unit_settings.scale_length = 100
            bpy.data.cameras["Camera"].draw_size = 0.01
            bpy.data.cameras["Camera"].clip_start = 0.01
            bpy.data.cameras["Camera"].clip_end = bpy.data.cameras["Camera"].clip_start * 2000
        elif self.unit == "mm":
            bpy.context.scene.unit_settings.scale_length = 1000
            bpy.data.cameras["Camera"].draw_size = 0.001
            bpy.data.cameras["Camera"].clip_start = 0.001
            bpy.data.cameras["Camera"].clip_end = bpy.data.cameras["Camera"].clip_start * 2000
        elif self.unit == "i":
            bpy.context.scene.unit_settings.scale_length = 12
            bpy.data.cameras["Camera"].draw_size = 0.0254
            bpy.data.cameras["Camera"].clip_start = 0.0254
            bpy.data.cameras["Camera"].clip_end = bpy.data.cameras["Camera"].clip_start * 2000
        elif self.unit == "f":
            bpy.data.cameras["Camera"].draw_size = 0.3048


    def parseModel( self ):

        #parse meshes

        self.parseMeshes( )

        #parse hierarchy

        self.parseNode( self.model["hierarchy"][0], None, -1)

        #convert created materials to Cycles materials

        if self.useBlenderCycles:

            self.createCycleMaterials()

        else:

            self.createBIMaterials()
        #create camera

        self.createCamera()

    def createCamera( self ) :

        views = self.model["views"]

        first = True

        for view in views:



            if ( first and len(bpy.data.cameras)>= 1 ):

                camera = bpy.data.cameras[0]

                camera_object  = bpy.context.scene.camera

                first = False

            else:

                camera = bpy.data.cameras.new(view["name"])

                camera_object = bpy.data.objects.new(view["name"], camera)

                bpy.context.scene.objects.link(camera_object)



            mode = view["mode"]

            if mode == "perspective":

                camera.type = "PERSP"

                w = float(self.options["vpWidth"])

                h = float(self.options["vpHeight"])

                ratio = w / h

                #camera.lens = 16/(ratio*math.tan(180/3.14159265359* view["fov"] /2))

                fieldOfViewY = view["fov"]* 3.14159265359 / 180

                camera.sensor_width = 32

                camera.angle = 2 * math.atan(math.tan(fieldOfViewY * 0.5) * ratio)


                #camera.lens = camera.sensor_width / ( 2 * math.tan(0.5* camera.angle))

            else:

                camera.type = "ORTHO"
                camera.ortho_scale = view["orthoHeight"]

            eye = mathutils.Vector(view["eye"])

            target = mathutils.Vector(view["target"])

            up = mathutils.Vector(view["up"])

            camera_object.matrix_world = self.matrixLookat(eye, target, up)



    def getImage( self, name ):

        img = self.images.get(name)

        if img is not None:

            return img

        absPath = self.sourceDir + "/" + name

        try:
            img = bpy.data.images.load(absPath)

            if self.pack_texture :

                bpy.ops.image.pack({'edit_image': img})

            self.images[name] = img

        except:
            raise NameError("Cannot load image %s" % absPath)

        return img

    def getEmptyMaterial( self, frontMaterialId, backMaterialId ):

        key = str(frontMaterialId)+"#"

        if self.back_materials:

            key +=  str(backMaterialId)

        material = self.materials.get(key);

        if material is None:

            material = bpy.data.materials.new(name=key)

            self.materials[ key ] = material

        return material

    def parseNode( self, node, parent, parentMaterial ):

        nodeName = node["name"]

        n = node["matrix"]

        nodeMaterial = node["material"]

        if "definition" in node:

            definitionId = node["definition"]

            node = self.model["definitions"][definitionId]

        children = None

        if  "children" in node:

            children = node["children"]

        objectData = None

        if( nodeMaterial == -1 ):

            nodeMaterial = parentMaterial

        if "mesh" in node:

            objectData = self.meshes[node["mesh"]]

        object = bpy.data.objects.new(nodeName, objectData)

        if parent is not None:

            object.parent = parent

        [pos,rot,scale] = mathutils.Matrix( [ [n[0],n[4],n[8],n[12]],
                                                [n[1],n[5],n[9],n[13]],
                                                [n[2],n[6],n[10],n[14]],
                                                [n[3],n[7],n[11],n[15]] ] ).decompose()

        object.matrix_local = mathutils.Matrix( [ [n[0],n[1],n[2],n[3]],
                                                [n[4],n[5],n[6],n[7]],
                                                [n[8],n[9],n[10],n[11]],
                                                [n[12],n[13],n[14],n[15]] ] )


        if objectData is not None and nodeMaterial != -1:

            k = 0

            for meshMaterial in objectData.materials:

                meshMaterial =  objectData.materials[k]

                temp = meshMaterial.name.split("#")

                frontMat = int(temp[0])

                backMat = -1

                if self.back_materials:
                    backMat = int(temp[1])

                if frontMat == -1 or backMat == -1:

                    if frontMat == -1:
                        frontMat = nodeMaterial

                    if backMat == -1:
                        backMat = nodeMaterial

                    object.material_slots[k].link = 'OBJECT'

                    object.material_slots[k].material = self.getEmptyMaterial( frontMat, backMat)

                k = k+1

        #object.location = pos
        #object.rotation_quaternion = rot
        #object.scale = scale

        #object.location = ( pos[0],pos[1],pos[2])

        if children is not None:

            for child in children:

                self.parseNode( child, object, nodeMaterial)

        self.scene.objects.link(object)

    def parseMeshes( self):

        self.meshes = []

        meshes = self.model["meshes"]

        for m in meshes:

            self.meshes.append( self.createMesh(m) )

    def createMesh( self, mesh):

        me = bpy.data.meshes.new("mesh")

        vertices = mesh["vertices"]

        faces = mesh["indices"]

        normals = mesh["normals"]

        sharpEdgesTemp = mesh["edges"]

        materials = mesh["materials"]

        backMaterials = mesh["backMaterials"]

        #computed mesh values

        edgeVertices = []

        loopVertexIndices = []

        loopEdgeIndices = []

        polygonLoopStarts = []

        polygonLoopTotals = []

        polygonMaterialIndices = []

        meshMaterials = {}

        nbEdges = 0

        nbLoops = 0

        nbPolygons = 0

        for f in range(0, len(faces) ):
            face = faces[f]
            polygonLoopStarts.append(nbLoops)
            polygonLoopTotals.append(len(face))

            frontMaterialId = materials[f]

            backMaterialId = backMaterials[f]

            key = str(frontMaterialId) + "#" + str(backMaterialId)

            materialId = meshMaterials.get(key)

            if( materialId is None ) :

                newMat = self.getEmptyMaterial(frontMaterialId,backMaterialId)

                materialId = len(me.materials)

                me.materials.append(newMat)

                meshMaterials[key] = materialId

            polygonMaterialIndices.append(materialId)

            nbLoops += len(face)

            nbPolygons += 1

            for i in range(0, len(face) ):
                loopVertexIndices.append(face[i])
                loopEdgeIndices.append(nbEdges)
                if( i != ( len(face) -1 ) ):
                    edgeVertices.extend([face[i],face[i+1]])
                else:
                    edgeVertices.extend([face[i],face[0]])
                nbEdges += 1


        sharpEdges = []

        for f in range(0, len(sharpEdgesTemp) ):
            if( sharpEdgesTemp[f] == 1 ):
                sharpEdges.append(True)
            else:
                sharpEdges.append(False)

        #print( "mesh:"+str(len(self.meshes)))
        #print( "nbEdges:"+str(nbEdges))
        #print( "nbLoops:"+str(nbLoops))
        #print( "nbPolygons:"+str(nbPolygons))
        #print( "edgeVertices:"+str(len((edgeVertices))))

        #create vertices

        me.vertices.add(len(vertices))

        me.vertices.foreach_set("co", unpack_list(vertices))

        #create edges

        me.edges.add(nbEdges)

        me.edges.foreach_set("vertices", edgeVertices )

        if self.use_sharp_edge :
            me.edges.foreach_set("use_edge_sharp", sharpEdges )

        if self.use_freestyle_mark :
            me.edges.foreach_set("use_freestyle_mark", sharpEdges )

        if self.use_seam :
            me.edges.foreach_set("use_seam", sharpEdges )

        #create loops

        me.loops.add(nbLoops)

        me.loops.foreach_set("vertex_index", loopVertexIndices)

        me.loops.foreach_set("edge_index", loopEdgeIndices)

        #create polygons

        me.polygons.add(nbPolygons)

        me.polygons.foreach_set("loop_start", polygonLoopStarts)

        me.polygons.foreach_set("loop_total", polygonLoopTotals)

        me.polygons.foreach_set("material_index", polygonMaterialIndices)

        #create two uv textures for front and back face

        me.uv_textures.new("UVMap")

        #me.uv_textures.new("BackUV")

        #set uv

        frontUvs = mesh["uvs"]
        frontLayerData = me.uv_layers[0].data

        #backUvs = mesh["backUvs"]
        #backLayerData = me.uv_layers[1].data

        for k in range(0, nbLoops):
            frontLayerData[k].uv = frontUvs[k]
            #backLayerData[k].uv = backUvs[k]


        #set custom split normals

        me.loops.foreach_get("normal", unpack_list(normals))

        me.normals_split_custom_set(normals)

        #me.show_normal_loop = True # debug normals

        me.validate(verbose=False,clean_customdata=False)  # *Very* important to not remove lnors here!

        me.use_auto_smooth = True

        me.show_edge_sharp = True


        return me

    def createBlendUpGlossy( self ):

        group = bpy.data.node_groups.new('BlendUpGlossy', 'ShaderNodeTree')
        group.use_fake_user = True
        nodes = []

        nodes.append(group.nodes.new('ShaderNodeBsdfTransparent'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('NodeGroupOutput'))
        nodes.append(group.nodes.new('ShaderNodeBsdfGlossy'))
        nodes.append(group.nodes.new('NodeGroupInput'))

        group.inputs.new('NodeSocketColor','Color')
        group.inputs.new('NodeSocketFloatFactor','Transparency')
        group.inputs.new('NodeSocketFloatFactor','Roughness')
        group.inputs.new('NodeSocketVector','Normal Map')

        group.outputs.new('NodeSocketShader','out')

        setattr(nodes[0], 'location', [-93.27900695800781, 22.7655029296875])
        setattr(nodes[1], 'location', [158.4275360107422, -18.004966735839844])
        setattr(nodes[2], 'location', [392.5262756347656, -23.345855712890625])
        setattr(nodes[3], 'location', [-98.65467834472656, -140.48617553710938])
        setattr(nodes[4], 'location', [-363.0636901855469, -19.837453842163086])

        group.links.new(group.nodes[4].outputs[1], group.nodes[1].inputs[0], False)
        group.links.new(group.nodes[1].outputs[0], group.nodes[2].inputs[0], False)
        group.links.new(group.nodes[0].outputs[0], group.nodes[1].inputs[1], False)
        group.links.new(group.nodes[4].outputs[0], group.nodes[3].inputs[0], False)
        group.links.new(group.nodes[4].outputs[2], group.nodes[3].inputs[1], False)
        group.links.new(group.nodes[4].outputs[3], group.nodes[3].inputs[2], False)
        group.links.new(group.nodes[3].outputs[0], group.nodes[1].inputs[2], False)

        setattr(group.inputs[0], 'default_value', [0.4793201982975006, 0.4793201982975006, 0.4793201982975006, 1.0])

        setattr(group.inputs[1], 'default_value', 1.0)
        setattr(group.inputs[1], 'max_value', 1.0)
        setattr(group.inputs[1], 'min_value', 0.0)

        setattr(group.inputs[2], 'default_value', 0.0)
        setattr(group.inputs[2], 'max_value', 1.0)
        setattr(group.inputs[2], 'min_value', 0.0)

        setattr(group.inputs[3], 'default_value', [0.0, 0.0, 0.0])
        setattr(group.inputs[3], 'max_value', 1.0)
        setattr(group.inputs[3], 'min_value', -1.0)

        return group

    def createBlendUpDiffuse( self ):

        group = bpy.data.node_groups.new('BlendUpDiffuse', 'ShaderNodeTree')
        group.use_fake_user = True
        nodes = []

        nodes.append(group.nodes.new('ShaderNodeBsdfTransparent'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('NodeGroupOutput'))
        nodes.append(group.nodes.new('ShaderNodeBsdfDiffuse'))
        nodes.append(group.nodes.new('NodeGroupInput'))

        group.inputs.new('NodeSocketColor','Color')
        group.inputs.new('NodeSocketFloatFactor','Transparency')
        group.inputs.new('NodeSocketFloatFactor','Roughness')
        group.inputs.new('NodeSocketVector','Normal Map')

        group.outputs.new('NodeSocketShader','out')

        setattr(nodes[0], 'location', [-93.27900695800781, 22.7655029296875])
        setattr(nodes[1], 'location', [158.4275360107422, -18.004966735839844])
        setattr(nodes[2], 'location', [392.5262756347656, -23.345855712890625])
        setattr(nodes[3], 'location', [-98.65467834472656, -140.48617553710938])
        setattr(nodes[4], 'location', [-363.0636901855469, -19.837453842163086])

        group.links.new(group.nodes[4].outputs[1], group.nodes[1].inputs[0], False)
        group.links.new(group.nodes[1].outputs[0], group.nodes[2].inputs[0], False)
        group.links.new(group.nodes[0].outputs[0], group.nodes[1].inputs[1], False)
        group.links.new(group.nodes[4].outputs[0], group.nodes[3].inputs[0], False)
        group.links.new(group.nodes[4].outputs[2], group.nodes[3].inputs[1], False)
        group.links.new(group.nodes[4].outputs[3], group.nodes[3].inputs[2], False)
        group.links.new(group.nodes[3].outputs[0], group.nodes[1].inputs[2], False)

        setattr(group.inputs[0], 'default_value', [0.4793201982975006, 0.4793201982975006, 0.4793201982975006, 1.0])

        setattr(group.inputs[1], 'default_value', 1.0)
        setattr(group.inputs[1], 'max_value', 1.0)
        setattr(group.inputs[1], 'min_value', 0.0)

        setattr(group.inputs[2], 'default_value', 0.0)
        setattr(group.inputs[2], 'max_value', 1.0)
        setattr(group.inputs[2], 'min_value', 0.0)

        setattr(group.inputs[3], 'default_value', [0.0, 0.0, 0.0])
        setattr(group.inputs[3], 'max_value', 1.0)
        setattr(group.inputs[3], 'min_value', -1.0)

        return group

    def createBlendUpMixDiffuseGlossy( self ):

        group = bpy.data.node_groups.new('BlendUpMixDiffuseGlossy', 'ShaderNodeTree')
        group.use_fake_user = True
        nodes = []

        nodes.append(group.nodes.new('ShaderNodeBsdfGlossy'))
        nodes.append(group.nodes.new('NodeGroupOutput'))
        nodes.append(group.nodes.new('ShaderNodeBsdfDiffuse'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('NodeGroupInput'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('ShaderNodeBsdfTransparent'))


        group.inputs.new('NodeSocketColor','Color')
        group.inputs.new('NodeSocketColor','Gloss Color')
        group.inputs.new('NodeSocketFloatFactor','Gloss')
        group.inputs.new('NodeSocketFloatFactor','Transparency')
        group.inputs.new('NodeSocketFloatFactor','Roughness')
        group.inputs.new('NodeSocketVector','Normal')

        group.outputs.new('NodeSocketShader','out')

        setattr(nodes[0], 'location', [-98.08839416503906, -284.52398681640625])
        setattr(nodes[1], 'location', [479.94244384765625, -22.178813934326172])
        setattr(nodes[2], 'location', [-98.65467834472656, -140.48617553710938])
        setattr(nodes[3], 'location', [104.83003997802734, -196.83013916015625])
        setattr(nodes[4], 'location', [-363.0636901855469, -19.837453842163086])
        setattr(nodes[5], 'location', [279.025634765625, -66.3199462890625])
        setattr(nodes[6], 'location', [97.43165588378906, -9.969608306884766])

        group.links.new(group.nodes[4].outputs[3], group.nodes[5].inputs[0], False)
        group.links.new(group.nodes[5].outputs[0], group.nodes[1].inputs[0], False)
        group.links.new(group.nodes[6].outputs[0], group.nodes[5].inputs[1], False)
        group.links.new(group.nodes[4].outputs[0], group.nodes[2].inputs[0], False)
        group.links.new(group.nodes[4].outputs[4], group.nodes[2].inputs[1], False)
        group.links.new(group.nodes[4].outputs[5], group.nodes[2].inputs[2], False)
        group.links.new(group.nodes[4].outputs[1], group.nodes[0].inputs[0], False)
        group.links.new(group.nodes[4].outputs[4], group.nodes[0].inputs[1], False)
        group.links.new(group.nodes[3].outputs[0], group.nodes[5].inputs[2], False)
        group.links.new(group.nodes[2].outputs[0], group.nodes[3].inputs[1], False)
        group.links.new(group.nodes[0].outputs[0], group.nodes[3].inputs[2], False)
        group.links.new(group.nodes[4].outputs[2], group.nodes[3].inputs[0], False)


        setattr(group.inputs[0], 'default_value', [0.4793201982975006, 0.4793201982975006, 0.4793201982975006, 1.0])
        setattr(group.inputs[1], 'default_value', [0.800000011920929, 0.800000011920929, 0.800000011920929, 1.0])
        setattr(group.inputs[2], 'default_value', 0.20000000298023224)
        setattr(group.inputs[2], 'max_value', 1.0)
        setattr(group.inputs[2], 'min_value', 0.0)

        setattr(group.inputs[3], 'default_value', 1.0)
        setattr(group.inputs[3], 'max_value', 1.0)
        setattr(group.inputs[3], 'min_value', 0.0)

        setattr(group.inputs[4], 'default_value', 0.0)
        setattr(group.inputs[4], 'max_value', 1.0)
        setattr(group.inputs[4], 'min_value', 0.0)

        setattr(group.inputs[5], 'default_value', [0.0, 0.0, 0.0])
        setattr(group.inputs[5], 'max_value', 1.0)
        setattr(group.inputs[5], 'min_value', -1.0)

        return group

    def createBlendUpMixDiffuseGlossy2( self ):

        group = bpy.data.node_groups.new('BlendUpMixDiffuseGlossy2', 'ShaderNodeTree')
        group.use_fake_user = True
        nodes = []

        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('ShaderNodeBsdfDiffuse'))
        nodes.append(group.nodes.new('ShaderNodeBsdfTransparent'))
        nodes.append(group.nodes.new('ShaderNodeLayerWeight'))
        nodes.append(group.nodes.new('NodeGroupOutput'))
        nodes.append(group.nodes.new('ShaderNodeBsdfGlossy'))
        nodes.append(group.nodes.new('NodeGroupInput'))


        group.inputs.new('NodeSocketColor','Color')
        group.inputs.new('NodeSocketColor','Gloss Color')
        group.inputs.new('NodeSocketFloatFactor','Transparency')
        group.inputs.new('NodeSocketFloatFactor','Roughness')
        group.inputs.new('NodeSocketFloatFactor','Blend')
        group.inputs.new('NodeSocketVector','Normal')

        group.outputs.new('NodeSocketShader','out')

        setattr(nodes[0], 'location', [58.88031005859375, -1.1132183074951172])
        setattr(nodes[1], 'location', [295.30865478515625, 43.30387878417969])
        setattr(nodes[2], 'location', [-212.7175750732422, 22.63483428955078])
        setattr(nodes[3], 'location', [67.42587280273438, 99.98251342773438])
        setattr(nodes[4], 'location', [-213.2921600341797, 171.57620239257812])
        setattr(nodes[5], 'location', [496.9807434082031, 9.520580291748047])
        setattr(nodes[6], 'location', [-216.29188537597656, -123.47525024414062])
        setattr(nodes[7], 'location', [-523.8729858398438, 6.868438720703125])

        group.links.new(group.nodes[6].outputs[0], group.nodes[0].inputs[2], False)
        group.links.new(group.nodes[4].outputs[1], group.nodes[0].inputs[0], False)
        group.links.new(group.nodes[3].outputs[0], group.nodes[1].inputs[1], False)
        group.links.new(group.nodes[7].outputs[0], group.nodes[2].inputs[0], False)
        group.links.new(group.nodes[2].outputs[0], group.nodes[0].inputs[1], False)
        group.links.new(group.nodes[0].outputs[0], group.nodes[1].inputs[2], False)
        group.links.new(group.nodes[1].outputs[0], group.nodes[5].inputs[0], False)
        group.links.new(group.nodes[7].outputs[2], group.nodes[1].inputs[0], False)
        group.links.new(group.nodes[7].outputs[3], group.nodes[2].inputs[1], False)
        group.links.new(group.nodes[7].outputs[5], group.nodes[2].inputs[2], False)
        group.links.new(group.nodes[7].outputs[3], group.nodes[6].inputs[1], False)
        group.links.new(group.nodes[7].outputs[5], group.nodes[6].inputs[2], False)
        group.links.new(group.nodes[7].outputs[4], group.nodes[4].inputs[0], False)
        group.links.new(group.nodes[7].outputs[5], group.nodes[4].inputs[1], False)
        group.links.new(group.nodes[7].outputs[1], group.nodes[6].inputs[0], False)


        setattr(group.inputs[0], 'default_value', [0.800000011920929, 0.800000011920929, 0.800000011920929, 1.0])
        setattr(group.inputs[1], 'default_value', [0.6382714509963989, 0.6382714509963989, 0.6382714509963989, 1.0])
        setattr(group.inputs[2], 'default_value', 1.0)
        setattr(group.inputs[2], 'max_value', 1.0)
        setattr(group.inputs[2], 'min_value', 0.0)
        setattr(group.inputs[3], 'default_value', 0.0)
        setattr(group.inputs[3], 'max_value', 1.0)
        setattr(group.inputs[3], 'min_value', 0.0)
        setattr(group.inputs[4], 'default_value', 0.10000000149011612)
        setattr(group.inputs[4], 'max_value', 1.0)
        setattr(group.inputs[4], 'min_value', 0.0)
        setattr(group.inputs[5], 'default_value', [0.0, 0.0, 0.0])
        setattr(group.inputs[5], 'max_value', 1.0)
        setattr(group.inputs[5], 'min_value', -1.0)

        return group

    def createBlendUpFabric( self ):

        group = bpy.data.node_groups.new('BlendUpFabric', 'ShaderNodeTree')
        group.use_fake_user = True
        nodes = []

        nodes.append(group.nodes.new('ShaderNodeBsdfVelvet'))
        nodes.append(group.nodes.new('ShaderNodeBsdfDiffuse'))
        nodes.append(group.nodes.new('ShaderNodeBsdfTransparent'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('NodeGroupOutput'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('ShaderNodeCombineHSV'))
        nodes.append(group.nodes.new('ShaderNodeSeparateHSV'))
        nodes.append(group.nodes.new('ShaderNodeMath'))
        nodes.append(group.nodes.new('ShaderNodeLayerWeight'))
        nodes.append(group.nodes.new('ShaderNodeBsdfGlossy'))
        nodes.append(group.nodes.new('NodeGroupInput'))




        group.inputs.new('NodeSocketColor','Color')
        group.inputs.new('NodeSocketFloatFactor','Transparency')
        group.inputs.new('NodeSocketFloatFactor','Roughness')
        group.inputs.new('NodeSocketFloatFactor','Velvet')
        group.inputs.new('NodeSocketFloatFactor','Blend')
        group.outputs.new('NodeSocketShader','out')
        group.inputs.new('NodeSocketVector','Normal')

        setattr(nodes[0], 'location', [-106.10821533203125, -137.16693115234375])
        setattr(nodes[1], 'location', [-114.49026489257812, -294.1087646484375])
        setattr(nodes[2], 'location', [-101.3060302734375, 58.19593048095703])
        setattr(nodes[3], 'location', [468.136962890625, -55.72111129760742])
        setattr(nodes[4], 'location', [418.14990234375, -235.820556640625])
        setattr(nodes[5], 'location', [655.2421875, -59.36756134033203])
        setattr(nodes[6], 'location', [102.14228820800781, -74.29711151123047])
        setattr(nodes[7], 'location', [-416.46148681640625, -162.48497009277344])
        setattr(nodes[8], 'location', [-662.0545043945312, -154.95553588867188])
        setattr(nodes[9], 'location', [-541.9961547851562, -322.1856384277344])
        setattr(nodes[10], 'location', [134.7645263671875, -201.5348663330078])
        setattr(nodes[11], 'location', [130.19033813476562, -338.1103515625])
        setattr(nodes[12], 'location', [-854.2901000976562, -1.4631919860839844])

        group.links.new(group.nodes[2].outputs[0], group.nodes[3].inputs[1], False)
        group.links.new(group.nodes[12].outputs[0], group.nodes[1].inputs[0], False)
        group.links.new(group.nodes[12].outputs[0], group.nodes[2].inputs[0], False)
        group.links.new(group.nodes[12].outputs[1], group.nodes[3].inputs[0], False)
        group.links.new(group.nodes[12].outputs[2], group.nodes[1].inputs[1], False)
        group.links.new(group.nodes[12].outputs[3], group.nodes[6].inputs[0], False)
        group.links.new(group.nodes[12].outputs[5], group.nodes[1].inputs[2], False)
        group.links.new(group.nodes[3].outputs[0], group.nodes[5].inputs[0], False)
        group.links.new(group.nodes[11].outputs[0], group.nodes[4].inputs[2], False)
        group.links.new(group.nodes[6].outputs[0], group.nodes[4].inputs[1], False)
        group.links.new(group.nodes[10].outputs[1], group.nodes[4].inputs[0], False)
        group.links.new(group.nodes[4].outputs[0], group.nodes[3].inputs[2], False)
        group.links.new(group.nodes[12].outputs[0], group.nodes[8].inputs[0], False)
        group.links.new(group.nodes[7].outputs[0], group.nodes[0].inputs[0], False)
        group.links.new(group.nodes[0].outputs[0], group.nodes[6].inputs[2], False)
        group.links.new(group.nodes[1].outputs[0], group.nodes[6].inputs[1], False)
        group.links.new(group.nodes[8].outputs[2], group.nodes[9].inputs[1], False)
        group.links.new(group.nodes[9].outputs[0], group.nodes[7].inputs[2], False)
        group.links.new(group.nodes[8].outputs[1], group.nodes[7].inputs[1], False)
        group.links.new(group.nodes[8].outputs[0], group.nodes[7].inputs[0], False)
        group.links.new(group.nodes[12].outputs[2], group.nodes[11].inputs[1], False)
        group.links.new(group.nodes[12].outputs[5], group.nodes[11].inputs[2], False)
        group.links.new(group.nodes[12].outputs[4], group.nodes[10].inputs[0], False)
        group.links.new(group.nodes[12].outputs[5], group.nodes[10].inputs[1], False)
        group.links.new(group.nodes[12].outputs[5], group.nodes[0].inputs[2], False)

        setattr(nodes[9], 'operation', 'MULTIPLY')
        setattr(nodes[9].inputs[0], 'default_value', 1.2)

        setattr(group.inputs[0], 'default_value', [1.0, 1.0, 1.0, 1.0])

        setattr(group.inputs[1], 'default_value', 1.0)
        setattr(group.inputs[1], 'max_value', 1.0)
        setattr(group.inputs[1], 'min_value', 0.0)

        setattr(group.inputs[2], 'default_value', 0.699999988079071)
        setattr(group.inputs[2], 'max_value', 1.0)
        setattr(group.inputs[2], 'min_value', 0.0)


        setattr(group.inputs[3], 'default_value', 0.800000011920929)
        setattr(group.inputs[3], 'max_value', 1.0)
        setattr(group.inputs[3], 'min_value', 0.0)

        setattr(group.inputs[4], 'default_value', 0.05000000074505806)
        setattr(group.inputs[4], 'max_value', 1.0)
        setattr(group.inputs[4], 'min_value', 0.0)

        setattr(group.inputs[5], 'default_value', [0.0, 0.0, 0.0])
        setattr(group.inputs[5], 'max_value', 1.0)
        setattr(group.inputs[5], 'min_value', -1.0)


        return group
    def createBlendUpGlass( self ):

        group = bpy.data.node_groups.new('BlendUpGlass', 'ShaderNodeTree')
        group.use_fake_user = True
        nodes = []

        nodes.append(group.nodes.new('ShaderNodeBsdfTransparent'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('ShaderNodeBsdfTransparent'))
        nodes.append(group.nodes.new('ShaderNodeBsdfGlossy'))
        nodes.append(group.nodes.new('ShaderNodeLightPath'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('NodeGroupOutput'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('ShaderNodeBsdfTransparent'))
        nodes.append(group.nodes.new('ShaderNodeLayerWeight'))
        nodes.append(group.nodes.new('ShaderNodeMath'))
        nodes.append(group.nodes.new('NodeGroupInput'))


        group.inputs.new('NodeSocketColor','Color')
        group.inputs.new('NodeSocketFloatFactor','Transparency')

        group.outputs.new('NodeSocketShader','out')

        setattr(nodes[0], 'location', [-0.8359482288360596, -84.36238098144531])
        setattr(nodes[1], 'location', [-78.04933166503906, 59.87400817871094])
        setattr(nodes[2], 'location', [-344.62945556640625, 56.638755798339844])
        setattr(nodes[3], 'location', [-327.3433837890625, -31.67084312438965])
        setattr(nodes[4], 'location', [-65.95742797851562, 397.6812438964844])
        setattr(nodes[5], 'location', [211.79600524902344, 80.58950805664062])
        setattr(nodes[6], 'location', [671.5985107421875, 48.43199920654297])
        setattr(nodes[7], 'location', [474.40582275390625, 70.64627838134766])
        setattr(nodes[8], 'location', [287.7782897949219, -96.51539611816406])
        setattr(nodes[9], 'location', [-605.169921875, 381.7786865234375])
        setattr(nodes[10], 'location', [-373.617919921875, 246.37042236328125])
        setattr(nodes[11], 'location', [-778.1406860351562, 83.45103454589844])

        setattr(nodes[10], 'operation', 'ADD')
        setattr(nodes[10].inputs[1], 'default_value', 0.075)

        group.links.new(group.nodes[4].outputs[1], group.nodes[5].inputs[0], False)
        group.links.new(group.nodes[0].outputs[0], group.nodes[5].inputs[2], False)
        group.links.new(group.nodes[1].outputs[0], group.nodes[5].inputs[1], False)
        group.links.new(group.nodes[2].outputs[0], group.nodes[1].inputs[1], False)
        group.links.new(group.nodes[3].outputs[0], group.nodes[1].inputs[2], False)
        group.links.new(group.nodes[11].outputs[0], group.nodes[3].inputs[0], False)
        group.links.new(group.nodes[11].outputs[0], group.nodes[2].inputs[0], False)
        group.links.new(group.nodes[11].outputs[0], group.nodes[0].inputs[0], False)
        group.links.new(group.nodes[10].outputs[0], group.nodes[1].inputs[0], False)
        group.links.new(group.nodes[9].outputs[1], group.nodes[10].inputs[0], False)
        group.links.new(group.nodes[11].outputs[1], group.nodes[7].inputs[0], False)
        group.links.new(group.nodes[5].outputs[0], group.nodes[7].inputs[2], False)
        group.links.new(group.nodes[7].outputs[0], group.nodes[6].inputs[0], False)
        group.links.new(group.nodes[8].outputs[0], group.nodes[7].inputs[1], False)


        setattr(group.inputs[0], 'default_value', [1.0, 1.0, 1.0, 1.0])

        setattr(group.inputs[1], 'default_value', 0.5)
        setattr(group.inputs[1], 'max_value', 1.0)
        setattr(group.inputs[1], 'min_value', 0.0)



        return group

    def createBlendUpAO( self ):

        group = bpy.data.node_groups.new('BlendUpAO', 'ShaderNodeTree')
        group.use_fake_user = True
        nodes = []

        nodes.append(group.nodes.new('ShaderNodeBsdfTransparent'))
        nodes.append(group.nodes.new('NodeGroupOutput'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('ShaderNodeAmbientOcclusion'))
        nodes.append(group.nodes.new('ShaderNodeEmission'))
        nodes.append(group.nodes.new('NodeGroupInput'))


        group.inputs.new('NodeSocketColor','Color')
        group.inputs.new('NodeSocketFloatFactor','Strength')
        group.inputs.new('NodeSocketFloatFactor','Transparency')
        group.inputs.new('NodeSocketVector','Normal')

        group.outputs.new('NodeSocketShader','out')

        setattr(nodes[0], 'location', [-93.27900695800781, 22.7655029296875])
        setattr(nodes[1], 'location', [614.4639892578125, -21.853071212768555])
        setattr(nodes[2], 'location', [158.82533264160156, -100.75477600097656])
        setattr(nodes[3], 'location', [382.217041015625, -30.9155330657959])
        setattr(nodes[4], 'location', [-91.35116577148438, -300.3694763183594])
        setattr(nodes[5], 'location', [-89.15872955322266, -168.53524780273438])
        setattr(nodes[6], 'location', [-363.0636901855469, -19.837453842163086])


        group.links.new(group.nodes[6].outputs[2], group.nodes[3].inputs[0], False)
        group.links.new(group.nodes[3].outputs[0], group.nodes[1].inputs[0], False)
        group.links.new(group.nodes[0].outputs[0], group.nodes[3].inputs[1], False)
        group.links.new(group.nodes[6].outputs[1], group.nodes[2].inputs[0], False)
        group.links.new(group.nodes[6].outputs[0], group.nodes[5].inputs[0], False)
        group.links.new(group.nodes[2].outputs[0], group.nodes[3].inputs[2], False)
        group.links.new(group.nodes[6].outputs[0], group.nodes[4].inputs[0], False)
        group.links.new(group.nodes[4].outputs[0], group.nodes[2].inputs[2], False)
        group.links.new(group.nodes[5].outputs[0], group.nodes[2].inputs[1], False)

        setattr(group.inputs[0], 'default_value', [0.800000011920929, 0.800000011920929, 0.800000011920929, 1.0])

        setattr(group.inputs[1], 'default_value', 1.0)
        setattr(group.inputs[1], 'max_value', 1.0)
        setattr(group.inputs[1], 'min_value', 0.0)

        setattr(group.inputs[2], 'default_value', 1.0)
        setattr(group.inputs[2], 'max_value', 1.0)
        setattr(group.inputs[2], 'min_value', 0.0)

        setattr(group.inputs[3], 'default_value', [0.0, 0.0, 0.0])
        setattr(group.inputs[3], 'max_value', 1.0)
        setattr(group.inputs[3], 'min_value', -1.0)

        return group

    def createBlendUpMonochrome( self ):

        group = bpy.data.node_groups.new('BlendUpMonochrome', 'ShaderNodeTree')
        group.use_fake_user = True
        nodes = []

        nodes.append(group.nodes.new('ShaderNodeBsdfDiffuse'))
        nodes.append(group.nodes.new('ShaderNodeBsdfTransparent'))
        nodes.append(group.nodes.new('NodeGroupOutput'))
        nodes.append(group.nodes.new('ShaderNodeAmbientOcclusion'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('NodeGroupInput'))


        group.inputs.new('NodeSocketColor','Color')
        group.inputs.new('NodeSocketFloatFactor','Direct Shadow')
        group.inputs.new('NodeSocketFloatFactor','Transparency')
        group.inputs.new('NodeSocketVector','Normal')

        group.outputs.new('NodeSocketShader','out')

        setattr(nodes[0], 'location', [-121.84773254394531, -201.3492889404297])
        setattr(nodes[1], 'location', [-91.5101089477539, 129.0993194580078])
        setattr(nodes[2], 'location', [635.9929809570312, 41.98583984375])
        setattr(nodes[3], 'location', [-110.73641967773438, -98.85674285888672])
        setattr(nodes[4], 'location', [149.810791015625, -45.246009826660156])
        setattr(nodes[5], 'location', [377.5273132324219, 46.166465759277344])
        setattr(nodes[6], 'location', [-414.78717041015625, 60.5648193359375])

        group.links.new(group.nodes[6].outputs[0], group.nodes[3].inputs[0], False)
        group.links.new(group.nodes[6].outputs[2], group.nodes[5].inputs[0], False)
        group.links.new(group.nodes[3].outputs[0], group.nodes[4].inputs[1], False)
        group.links.new(group.nodes[0].outputs[0], group.nodes[4].inputs[2], False)
        group.links.new(group.nodes[4].outputs[0], group.nodes[5].inputs[2], False)
        group.links.new(group.nodes[1].outputs[0], group.nodes[5].inputs[1], False)
        group.links.new(group.nodes[5].outputs[0], group.nodes[2].inputs[0], False)
        group.links.new(group.nodes[6].outputs[0], group.nodes[0].inputs[0], False)
        group.links.new(group.nodes[6].outputs[3], group.nodes[0].inputs[2], False)
        group.links.new(group.nodes[6].outputs[1], group.nodes[4].inputs[0], False)


        setattr(group.inputs[0], 'default_value', [0.800000011920929, 0.800000011920929, 0.800000011920929, 1.0])

        setattr(group.inputs[1], 'default_value', 0.2)
        setattr(group.inputs[1], 'max_value', 1.0)
        setattr(group.inputs[1], 'min_value', 0.0)

        setattr(group.inputs[2], 'default_value', 1.0)
        setattr(group.inputs[2], 'max_value', 1.0)
        setattr(group.inputs[2], 'min_value', 0.0)

        setattr(group.inputs[3], 'default_value', [0.0, 0.0, 0.0])
        setattr(group.inputs[3], 'max_value', 1.0)
        setattr(group.inputs[3], 'min_value', -1.0)

        return group

    def createBlendUpLight( self ):

        group = bpy.data.node_groups.new('BlendUpLight', 'ShaderNodeTree')
        group.use_fake_user = True
        nodes = []
        nodes.append(group.nodes.new('ShaderNodeBsdfTransparent'))
        nodes.append(group.nodes.new('ShaderNodeLightPath'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('NodeGroupOutput'))
        nodes.append(group.nodes.new('ShaderNodeEmission'))
        nodes.append(group.nodes.new('NodeGroupInput'))


        group.inputs.new('NodeSocketColor','Color')
        group.inputs.new('NodeSocketFloatFactor','Strength')

        group.outputs.new('NodeSocketShader','out')

        setattr(nodes[0], 'location', [-316.57318115234375, -32.83460998535156])
        setattr(nodes[1], 'location', [-322.07952880859375, 387.5373229980469])
        setattr(nodes[2], 'location', [-67.0149154663086, 147.7364501953125])
        setattr(nodes[3], 'location', [200.0, 143.9700164794922])
        setattr(nodes[4], 'location', [-316.3206787109375, 106.69867706298828])
        setattr(nodes[5], 'location', [-655.5391235351562, 87.66107940673828])

        group.links.new(group.nodes[1].outputs[0], group.nodes[2].inputs[0], False)
        group.links.new(group.nodes[0].outputs[0], group.nodes[2].inputs[2], False)
        group.links.new(group.nodes[4].outputs[0], group.nodes[2].inputs[1], False)
        group.links.new(group.nodes[2].outputs[0], group.nodes[3].inputs[0], False)
        group.links.new(group.nodes[5].outputs[0], group.nodes[4].inputs[0], False)
        group.links.new(group.nodes[5].outputs[1], group.nodes[4].inputs[1], False)

        setattr(group.inputs[0], 'default_value', [1.0, 1.0, 1.0, 1.0])

        setattr(group.inputs[1], 'default_value', 1.0)
        setattr(group.inputs[1], 'max_value', 1000000.0)
        setattr(group.inputs[1], 'min_value', 0.0)

        return group

    def createBlendUpToon( self ):

        #not used for now...

        group = bpy.data.node_groups.new('BlendUpToon', 'ShaderNodeTree')
        group.use_fake_user = True
        nodes = []

        nodes.append(group.nodes.new('NodeGroupOutput'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('NodeGroupInput'))
        nodes.append(group.nodes.new('ShaderNodeBsdfToon'))
        nodes.append(group.nodes.new('ShaderNodeBsdfTransparent'))

        group.inputs.new('NodeSocketColor','Color')
        group.inputs.new('NodeSocketFloatFactor','Size')
        group.inputs.new('NodeSocketFloatFactor','Smooth')
        group.inputs.new('NodeSocketFloatFactor','Transparency')

        group.outputs.new('NodeSocketShader','out')

        setattr(nodes[0], 'location', [429.60736083984375, 2.82112455368042])
        setattr(nodes[1], 'location', [231.41314697265625, 14.527313232421875])
        setattr(nodes[2], 'location', [-213.65118408203125, 55.83436965942383])
        setattr(nodes[3], 'location', [8.007874488830566, -115.88105773925781])
        setattr(nodes[4], 'location', [16.742874145507812, 89.47240447998047])

        group.links.new(group.nodes[2].outputs[0], group.nodes[3].inputs[0], False)
        group.links.new(group.nodes[2].outputs[1], group.nodes[3].inputs[1], False)
        group.links.new(group.nodes[2].outputs[2], group.nodes[3].inputs[2], False)
        group.links.new(group.nodes[2].outputs[4], group.nodes[3].inputs[3], False)
        group.links.new(group.nodes[1].outputs[0], group.nodes[0].inputs[0], False)
        group.links.new(group.nodes[2].outputs[3], group.nodes[1].inputs[0], False)
        group.links.new(group.nodes[4].outputs[0], group.nodes[1].inputs[1], False)
        group.links.new(group.nodes[3].outputs[0], group.nodes[1].inputs[2], False)

        setattr(group.inputs[0], 'default_value', [0.800000011920929, 0.800000011920929, 0.800000011920929, 1.0])

        setattr(group.inputs[1], 'default_value', 0.5)
        setattr(group.inputs[1], 'max_value', 1.0)
        setattr(group.inputs[1], 'min_value', 0.0)

        setattr(group.inputs[2], 'default_value', 0.0)
        setattr(group.inputs[2], 'max_value', 1.0)
        setattr(group.inputs[2], 'min_value', 0.0)

        setattr(group.inputs[3], 'default_value', 1.0)
        setattr(group.inputs[3], 'max_value', 1.0)
        setattr(group.inputs[3], 'min_value', 0.0)

        setattr(group.inputs[4], 'default_value', [0.0, 0.0, 0.0])
        setattr(group.inputs[4], 'max_value', 1.0)
        setattr(group.inputs[4], 'min_value', -1.0)

        return group

    def createBlendUpPBR( self ):

        group = bpy.data.node_groups.new('BlendUpPBR', 'ShaderNodeTree')
        group.use_fake_user = True
        nodes = []
        nodes.append(group.nodes.new('ShaderNodeBsdfDiffuse'))
        nodes.append(group.nodes.new('ShaderNodeBsdfGlossy'))
        nodes.append(group.nodes.new('ShaderNodeSeparateHSV'))
        nodes.append(group.nodes.new('ShaderNodeMath'))
        nodes.append(group.nodes.new('ShaderNodeMath'))
        nodes.append(group.nodes.new('ShaderNodeMath'))
        nodes.append(group.nodes.new('ShaderNodeFresnel'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('ShaderNodeEmission'))
        nodes.append(group.nodes.new('ShaderNodeMath'))
        nodes.append(group.nodes.new('ShaderNodeCombineHSV'))
        nodes.append(group.nodes.new('ShaderNodeMixRGB'))
        nodes.append(group.nodes.new('ShaderNodeMath'))
        nodes.append(group.nodes.new('ShaderNodeMath'))
        nodes.append(group.nodes.new('NodeGroupInput'))
        nodes.append(group.nodes.new('ShaderNodeAddShader'))
        nodes.append(group.nodes.new('ShaderNodeBsdfTransparent'))
        nodes.append(group.nodes.new('ShaderNodeMixShader'))
        nodes.append(group.nodes.new('NodeGroupOutput'))

        setattr(nodes[0], 'location', [-174.95565795898438, 380.4754943847656])
        setattr(nodes[1], 'location', [-90.94093322753906, -41.52635955810547])
        setattr(nodes[2], 'location', [-773.2938842773438, -332.9705810546875])
        setattr(nodes[3], 'location', [-552.3074340820312, -566.122314453125])
        setattr(nodes[4], 'location', [-275.2654113769531, -404.73870849609375])
        setattr(nodes[5], 'location', [-269.20556640625, -661.11865234375])
        setattr(nodes[6], 'location', [159.6534881591797, -264.4090881347656])
        setattr(nodes[7], 'location', [372.57501220703125, 26.189916610717773])
        setattr(nodes[8], 'location', [382.9889831542969, -190.98712158203125])
        setattr(nodes[9], 'location', [-32.4528694152832, -566.8570556640625])
        setattr(nodes[10], 'location', [-507.0903625488281, -307.22235107421875])
        setattr(nodes[11], 'location', [-460.05743408203125, 442.8718566894531])
        setattr(nodes[12], 'location', [-779.4415893554688, 372.6409606933594])
        setattr(nodes[13], 'location', [-447.469970703125, 97.66339111328125])
        setattr(nodes[14], 'location', [-1017.5684814453125, 13.1002197265625])
        setattr(nodes[15], 'location', [601.329833984375, -89.056640625])
        setattr(nodes[16], 'location', [599.4542846679688, 90.07467651367188])
        setattr(nodes[17], 'location', [959.8967895507812, 1.5410175323486328])
        setattr(nodes[18], 'location', [1204.2589111328125, -4.1744384765625])

        group.inputs.new('NodeSocketColor','Albedo')
        group.inputs.new('NodeSocketFloatFactor','Transparency')
        group.inputs.new('NodeSocketColor','Specular')
        group.inputs.new('NodeSocketFloatFactor','Smoothness')
        group.inputs.new('NodeSocketVector','Normal')
        group.inputs.new('NodeSocketColor','Occlusion')
        group.inputs.new('NodeSocketFloat','Occlusion Strength')
        group.inputs.new('NodeSocketColor','Emission')
        group.inputs.new('NodeSocketFloat','Emission Strength')

        group.outputs.new('NodeSocketShader','out')

        group.links.new(group.nodes[2].outputs[2], group.nodes[3].inputs[0], False)
        group.links.new(group.nodes[3].outputs[0], group.nodes[4].inputs[0], False)
        group.links.new(group.nodes[4].outputs[0], group.nodes[9].inputs[0], False)
        group.links.new(group.nodes[5].outputs[0], group.nodes[9].inputs[1], False)
        group.links.new(group.nodes[3].outputs[0], group.nodes[5].inputs[1], False)
        group.links.new(group.nodes[2].outputs[0], group.nodes[10].inputs[0], False)
        group.links.new(group.nodes[2].outputs[1], group.nodes[10].inputs[1], False)
        group.links.new(group.nodes[14].outputs[3], group.nodes[13].inputs[1], False)
        group.links.new(group.nodes[0].outputs[0], group.nodes[7].inputs[1], False)
        group.links.new(group.nodes[1].outputs[0], group.nodes[7].inputs[2], False)
        group.links.new(group.nodes[11].outputs[0], group.nodes[0].inputs[0], False)
        group.links.new(group.nodes[6].outputs[0], group.nodes[7].inputs[0], False)
        group.links.new(group.nodes[10].outputs[0], group.nodes[1].inputs[0], False)
        group.links.new(group.nodes[13].outputs[0], group.nodes[1].inputs[1], False)
        group.links.new(group.nodes[13].outputs[0], group.nodes[0].inputs[1], False)
        group.links.new(group.nodes[14].outputs[4], group.nodes[0].inputs[2], False)
        group.links.new(group.nodes[14].outputs[4], group.nodes[1].inputs[2], False)
        group.links.new(group.nodes[14].outputs[4], group.nodes[6].inputs[1], False)
        group.links.new(group.nodes[14].outputs[2], group.nodes[2].inputs[0], False)
        group.links.new(group.nodes[7].outputs[0], group.nodes[15].inputs[0], False)
        group.links.new(group.nodes[8].outputs[0], group.nodes[15].inputs[1], False)
        group.links.new(group.nodes[14].outputs[7], group.nodes[8].inputs[0], False)
        group.links.new(group.nodes[14].outputs[8], group.nodes[8].inputs[1], False)
        group.links.new(group.nodes[9].outputs[0], group.nodes[6].inputs[0], False)
        group.links.new(group.nodes[14].outputs[6], group.nodes[12].inputs[1], False)
        group.links.new(group.nodes[14].outputs[5], group.nodes[12].inputs[0], False)
        group.links.new(group.nodes[14].outputs[0], group.nodes[11].inputs[2], False)
        group.links.new(group.nodes[12].outputs[0], group.nodes[11].inputs[1], False)
        group.links.new(group.nodes[17].outputs[0], group.nodes[18].inputs[0], False)
        group.links.new(group.nodes[14].outputs[1], group.nodes[17].inputs[0], False)
        group.links.new(group.nodes[15].outputs[0], group.nodes[17].inputs[2], False)
        group.links.new(group.nodes[16].outputs[0], group.nodes[17].inputs[1], False)

        setattr(group.inputs[0], 'default_value', [0.4793201982975006, 0.4793201982975006, 0.4793201982975006, 1.0])

        setattr(group.inputs[1], 'default_value', 1.0)
        setattr(group.inputs[1], 'max_value', 1.0)
        setattr(group.inputs[1], 'min_value', 0.0)

        setattr(group.inputs[2], 'default_value', [0.04373502731323242, 0.04373502731323242, 0.04373502731323242, 1.0])

        setattr(group.inputs[3], 'default_value', 0.5)
        setattr(group.inputs[3], 'max_value', 1.0)
        setattr(group.inputs[3], 'min_value', 0.0)

        setattr(group.inputs[4], 'default_value', [0.0, 0.0, 0.0])
        setattr(group.inputs[4], 'max_value', 1.0)
        setattr(group.inputs[4], 'min_value', -1.0)

        setattr(group.inputs[5], 'default_value', [1.0, 1.0, 1.0, 1.0])

        setattr(group.inputs[6], 'default_value', 1.0)
        setattr(group.inputs[6], 'max_value', 10000.0)
        setattr(group.inputs[6], 'min_value', 0.0)

        setattr(group.inputs[7], 'default_value', [0.0, 0.0, 0.0, 1.0])

        setattr(group.inputs[8], 'default_value', 1.0)
        setattr(group.inputs[8], 'max_value', 10000.0)
        setattr(group.inputs[8], 'min_value', 0.0)

        setattr(nodes[3], 'operation', 'POWER')

        setattr(nodes[4], 'operation', 'ADD')
        setattr(nodes[4].inputs[1], 'default_value', 1.0)

        setattr(nodes[5], 'operation', 'SUBTRACT')
        setattr(nodes[5].inputs[0], 'default_value', 1.0)


        setattr(nodes[10].inputs[2], 'default_value', 1.0)

        setattr(nodes[11], 'blend_type', 'MULTIPLY')
        setattr(nodes[11].inputs[0], 'default_value', 1.0)

        setattr(nodes[12], 'operation', 'POWER')
        setattr(nodes[12].inputs[1], 'default_value', 0.5)

        setattr(nodes[13], 'operation', 'SUBTRACT')
        setattr(nodes[13].inputs[0], 'default_value', 1.0)
        setattr(nodes[13].inputs[1], 'default_value', 1.0)

        return group


    def cleanSpaces( self, str):

        return str.lstrip().rstrip()


    def parseMaterialDefinitions( self ):

        materials = []

        matFile = self.sourceDir+"/materials2.txt"

        if self.useBlenderCycles == False:

            matFile = self.sourceDir+"/materials.txt"

        with codecs.open(matFile, "r", "utf-8") as f:

            materialLines = f.readlines()

            for line in materialLines:

                mat = {}

                line = self.cleanSpaces(line)

                parameters = line.split(";")

                for param in parameters:

                    if not "=" in param: continue

                    vals = param.split("=")

                    if len(vals) != 2 : continue

                    valType = self.cleanSpaces(vals[0])

                    valValue = self.cleanSpaces(vals[1])

                    mat[valType] = valValue

                materials.append(mat)

        return materials

    def getMaterialGroup( self, id, definition, nodes ):

        mat = nodes.new('ShaderNodeGroup')

        group = self.materialGroups.get(id)

        if group is None:

            group = bpy.data.node_groups.new(definition["Name"], 'ShaderNodeTree')

            group.use_fake_user = True

            group.outputs.new('NodeSocketShader','out')

            shader = group.nodes.new('ShaderNodeGroup')

            outputNode = group.nodes.new('NodeGroupOutput')

            shader.node_tree = bpy.data.node_groups[definition["Type"]]

            shader.location = (0,150)

            outputNode.location = (200,150)

            textureNodes = {}

            #TODO: Shouldn't be always True for front face here, it will create a UV bug sometimes

            self.connectNodes(definition,shader,textureNodes, group.nodes, group.links, True )

            group.links.new(group.nodes[0].outputs[0], outputNode.inputs[0], False)

            self.materialGroups[id] = group

        mat.node_tree = group

        return mat

    def getMaterialGroupBI( self, id, definition, nodes, textureNodes ):

        mat = nodes.new('ShaderNodeGroup')

        group = self.materialGroups.get(id)

        #bpy.data.materials['Material'].node_tree.nodes.new("ShaderNodeGeometry")
        #bpy.data.materials['Material'].node_tree.nodes.new("ShaderNodeMaterial")
        #toto.material = bpy.data.materials.new("BI_profile")

        if group is None:

            group = bpy.data.node_groups.new(definition["Name"], 'ShaderNodeTree')

            group.use_fake_user = True

            #create output params

            group.outputs.new('NodeSocketColor','Color')

            group.outputs.new('NodeSocketFloatFactor','Alpha')

            #create output node

            outputNode = group.nodes.new('NodeGroupOutput')

            outputNode.location = (200,150)

            #create material node

            materialNode = group.nodes.new("ShaderNodeMaterial")

            materialNode.location = (0,150)

            materialNode.material = bpy.data.materials.new(definition["Name"]+"_profile")

            #create geometry node

            geometryNode = group.nodes.new("ShaderNodeGeometry")

            geometryNode.location = (-900,-200)

            #connect geometry normal

            group.links.new(geometryNode.outputs["Normal"], materialNode.inputs["Normal"], False)

            #connect output color

            group.links.new(materialNode.outputs["Color"], outputNode.inputs["Color"], False)


            #connect the rest based on the definition informations

            self.connectNodesBI(definition,materialNode,textureNodes, group.nodes, group.links, geometryNode, materialNode, outputNode)

            self.internalBImaterialGroups[id] = materialNode

            self.materialGroups[id] = group

        mat.node_tree = group

        return mat



    def connectNodes( self, definition , shader, textures, nodes, links, isFront ):

        def lin(x):
            a = 0.055
            if x <=0.04045 :
                y = x * (1.0 / 12.92)
            else:
                y = pow( (x + a) * (1.0 / (1 + a)), 2.4)
            return y

        #get global scale

        scaleS = 1

        scaleT = 1

        UVScaleVal = definition.get("UVScale")

        if UVScaleVal is not None:

            st = self.cleanSpaces(UVScaleVal[UVScaleVal.find("(")+1:UVScaleVal.find(")")])

            stv = re.findall(r"[-+]?\d*\.\d+|\d+",st)

            if( len(stv) != 2):
                print(stv)
                print(" parameter value UVScale badly defined, expected 2 components!")

            scaleS = float(stv[0])

            scaleT = float(stv[1])


        for param in definition:

            if param == "Type" : continue
            if param == "ID" : continue
            if param == "Name" : continue
            if param == "UVScale" : continue

            value = definition[param]

            shaderInput = shader.inputs.get( param )

            if shaderInput is None:
                print(" parameter "+param+" not found!")
                continue

            inputType = shaderInput.type

            if inputType == "RGBA":

                if "TextureColor(" in value:

                    value = self.cleanSpaces(value[value.find("TextureColor(")+13:value.rfind(")")])

                    node_texture = textures.get(value)

                    if  node_texture is None:

                        nbTextures = len( textures )

                        yTex = nbTextures * -300 + 300

                        image = self.getImage( value )

                        node_texture = nodes.new(type='ShaderNodeTexImage')

                        node_texture.image = image

                        node_texture.location = -300, yTex

                        node_uv = nodes.new(type='ShaderNodeUVMap')

                        node_uv.uv_map = "UVMap"

                        node_uv.location = -900,yTex

                        node_mapping = nodes.new(type='ShaderNodeMapping')

                        node_mapping.scale = (scaleS,scaleT,1)

                        node_mapping.location = -700,yTex

                        textures[value] = node_texture

                        links.new(node_uv.outputs[0], node_mapping.inputs["Vector"])

                        links.new(node_mapping.outputs[0], node_texture.inputs["Vector"])

                    links.new(node_texture.outputs[0], shaderInput)


                elif "Color(" in value:

                    v = re.findall(r"[-+]?\d*\.\d+|\d+",value)

                    if( len(v) != 3):
                        print(v)
                        print(" parameter value"+value+" badly defined, expected 3 components!")
                        continue

                    shaderInput.default_value[0] = lin( float(v[0]) / 255 )
                    shaderInput.default_value[1] = lin( float(v[1]) / 255 )
                    shaderInput.default_value[2] = lin( float(v[2]) / 255 )

                else:

                    print(" parameter value "+value+" badly defined!")
                    continue

            elif inputType == "VALUE":

                if "TextureAlpha(" in value:

                    value = self.cleanSpaces(value[value.find("TextureAlpha(")+13:value.rfind(")")])

                    node_texture = textures.get(value)

                    if  node_texture is None:

                        nbTextures = len( textures )

                        yTex = nbTextures * -300 + 300

                        image = self.getImage( value )

                        node_texture = nodes.new(type='ShaderNodeTexImage')

                        node_texture.image = image

                        node_texture.location = -300, yTex

                        node_uv = nodes.new(type='ShaderNodeUVMap')

                        node_uv.uv_map = "UVMap"

                        node_uv.location = -900,yTex

                        node_mapping = nodes.new(type='ShaderNodeMapping')

                        node_mapping.scale = (scaleS,scaleT,1)

                        node_mapping.location = -700,yTex

                        textures[value] = node_texture

                        links.new(node_uv.outputs[0], node_mapping.inputs["Vector"])

                        links.new(node_mapping.outputs[0], node_texture.inputs["Vector"])

                    links.new(node_texture.outputs[1], shaderInput)

                else:

                    v = re.findall(r"[-+]?\d*\.\d+|\d+",value)

                    if( len(v) != 1):
                        print(v)
                        print(" parameter value"+value+" badly defined, expected 1 component!")
                        continue

                    shaderInput.default_value = float(v[0])

            elif inputType == "VECTOR":

                if "TextureNormal(" in value:

                    value = self.cleanSpaces(value[value.find("TextureNormal(")+14:value.rfind(")")])

                    node_normal = textures.get(value)

                    if  node_normal is None:

                        nbTextures = len( textures )

                        yTex = nbTextures * -300 + 300

                        image = self.getImage( value )



                        node_normal = nodes.new(type='ShaderNodeNormalMap')

                        node_normal.location = -250, yTex


                        node_texture = nodes.new(type='ShaderNodeTexImage')

                        node_texture.image = image

                        node_texture.location = -500, yTex

                        node_texture.color_space = "NONE"

                        node_uv = nodes.new(type='ShaderNodeUVMap')

                        node_uv.uv_map = "UVMap"

                        node_uv.location = -1200,yTex

                        node_mapping = nodes.new(type='ShaderNodeMapping')


                        node_mapping.scale = (scaleS,scaleT,1)

                        node_mapping.location = -900,yTex

                        textures[value] = node_normal

                        links.new(node_uv.outputs[0], node_mapping.inputs["Vector"])

                        links.new(node_mapping.outputs[0], node_texture.inputs["Vector"])

                        links.new(node_texture.outputs[0], node_normal.inputs[1])

                    links.new(node_normal.outputs[0], shaderInput)

                else:

                    v = re.findall(r"[-+]?\d*\.\d+|\d+",value)

                    if( len(v) != 3):
                        print(v)
                        print(" parameter value"+value+" badly defined, expected 3 component!")
                        continue

                    shaderInput.default_value[0] = float(v[0])
                    shaderInput.default_value[1] = float(v[1])
                    shaderInput.default_value[2] = float(v[2])

            else:
                print( "Parameter " + param + " has an unsupported input type " + shaderInput.type )

    def connectNodesBI( self, definition , shader, textures, nodes, links, geometryNode, BIMaterial, groupOutput ):

        def lin(x):
            a = 0.055
            if x <=0.04045 :
                y = x * (1.0 / 12.92)
            else:
                y = pow( (x + a) * (1.0 / (1 + a)), 2.4)
            return y

        #get global scale

        scaleS = 1

        scaleT = 1

        UVScaleVal = definition.get("UVScale")

        if UVScaleVal is not None:

            st = self.cleanSpaces(UVScaleVal[UVScaleVal.find("(")+1:UVScaleVal.find(")")])

            stv = re.findall(r"[-+]?\d*\.\d+|\d+",st)

            if( len(stv) != 2):
                print(stv)
                print(" parameter value UVScale badly defined, expected 2 components!")

            scaleS = float(stv[0])

            scaleT = float(stv[1])


        alphaConnected = False

        for param in definition:

            if param == "Type" : continue
            if param == "ID" : continue
            if param == "Name" : continue
            if param == "UVScale" : continue

            value = definition[param]


            if param == "Transparency":
                inputType = "VALUE"
            else:
                shaderInput = shader.inputs.get( param )
                if shaderInput is None:
                    print(" parameter "+param+" not found!")
                    continue
                inputType = shaderInput.type

            if inputType == "RGBA":

                if "TextureColor(" in value:

                    value = self.cleanSpaces(value[value.find("TextureColor(")+13:value.rfind(")")])

                    node_texture = textures.get(value)

                    if  node_texture is None:

                        nbTextures = len( textures )

                        yTex = nbTextures * -300 + 300

                        image = self.getImage( value )

                        node_texture = nodes.new(type='ShaderNodeTexture')

                        tex = self.BItextures.get(definition["Name"])

                        if tex is None:

                            tex = bpy.data.textures.new(value,'IMAGE')

                            tex.image = image

                            self.BItextures[definition["Name"]] = tex

                        node_texture.texture = tex

                        node_texture.location = -300, yTex

                        geometryNode.uv_layer = "UVMap"

                        node_mapping = nodes.new(type='ShaderNodeMapping')

                        node_mapping.scale = (scaleS,scaleT,1)

                        node_mapping.location = -900,yTex

                        #UV OFFSET

                        node_add_uv_offset = nodes.new(type='ShaderNodeVectorMath')

                        node_add_uv_offset.operation = "ADD"

                        setattr(node_add_uv_offset.inputs[1], 'default_value', [1.0, 1.0, 0.0])
                                                #
                        node_add_uv_offset.location = -1100,yTex

                        node_subs_uv_offset = nodes.new(type='ShaderNodeVectorMath')

                        node_subs_uv_offset.operation = "SUBTRACT"

                        setattr(node_subs_uv_offset.inputs[1], 'default_value', [1.0, 1.0, 0.0])

                        node_subs_uv_offset.location = -500,yTex


                        links.new(geometryNode.outputs[5], BIMaterial.inputs["Normal"])


                        #uv offset
                        links.new(geometryNode.outputs[4], node_add_uv_offset.inputs[0])
                        links.new(node_add_uv_offset.outputs[0], node_mapping.inputs["Vector"])
                        links.new(node_mapping.outputs[0], node_subs_uv_offset.inputs[0])
                        links.new(node_subs_uv_offset.outputs[0], node_texture.inputs["Vector"])

                        textures[value] = node_texture

                    links.new(node_texture.outputs[1], shader.inputs[0])

                    links.new(node_texture.outputs["Value"], groupOutput.inputs["Alpha"], False)

                    alphaConnected = True
                elif "Color(" in value:

                    v = re.findall(r"[-+]?\d*\.\d+|\d+",value)

                    if( len(v) != 3):
                        print(v)
                        print(" parameter value"+value+" badly defined, expected 3 components!")
                        continue

                    r = lin( float(v[0]) / 255 )
                    g = lin( float(v[1]) / 255 )
                    b = lin( float(v[2]) / 255 )

                    if param == "Color":
                        shader.material.diffuse_color[0] = r
                        shader.material.diffuse_color[1] = g
                        shader.material.diffuse_color[2] = b
                    else:
                        shaderInput.default_value[0] = r
                        shaderInput.default_value[1] = g
                        shaderInput.default_value[2] = b

                        #
                        #shaderInput.default_value[1] = lin( float(v[1]) / 255 )
                        #shaderInput.default_value[2] = lin( float(v[2]) / 255 )

                else:

                    print(" parameter value "+value+" badly defined!")
                    continue

            elif inputType == "VALUE":

                if "TextureAlpha(" in value:

                    value = self.cleanSpaces(value[value.find("TextureAlpha(")+13:value.rfind(")")])

                    node_texture = textures.get(value)

                    if param == "Transparency":
                        shader.material.use_transparency = True


                    if  node_texture is None:

                        nbTextures = len( textures )

                        yTex = nbTextures * -300 + 300

                        image = self.getImage( value )

                        node_texture = nodes.new(type='ShaderNodeTexture')

                        tex = self.BItextures.get(definition["Name"])

                        if tex is None:

                            tex = bpy.data.textures.new(value,'IMAGE')

                            tex.image = image

                            self.BItextures[definition["Name"]] = tex



                        node_texture.location = -300, yTex

                        geometryNode.uv_layer = "UVMap"

                        node_mapping = nodes.new(type='ShaderNodeMapping')



                        node_mapping.scale = (scaleS,scaleT,1)

                        node_mapping.location = -700,yTex

                        #UV OFFSET

                        node_add_uv_offset = nodes.new(type='ShaderNodeVectorMath')

                        node_add_uv_offset.operation = "ADD"

                        setattr(node_add_uv_offset.inputs[1], 'default_value', [1.0, 1.0, 0.0])
                                                #
                        node_add_uv_offset.location = -1100,yTex

                        node_subs_uv_offset = nodes.new(type='ShaderNodeVectorMath')

                        node_subs_uv_offset.operation = "SUBTRACT"

                        setattr(node_subs_uv_offset.inputs[1], 'default_value', [1.0, 1.0, 0.0])

                        node_subs_uv_offset.location = -500,yTex

                        textures[value] = node_texture


                        #UV OFFSET

                        node_add_uv_offset = nodes.new(type='ShaderNodeVectorMath')

                        node_add_uv_offset.operation = "ADD"

                        setattr(node_add_uv_offset.inputs[1], 'default_value', [1.0, 1.0, 0.0])
                                                #
                        node_add_uv_offset.location = -1100,yTex

                        node_subs_uv_offset = nodes.new(type='ShaderNodeVectorMath')

                        node_subs_uv_offset.operation = "SUBTRACT"

                        setattr(node_subs_uv_offset.inputs[1], 'default_value', [1.0, 1.0, 0.0])

                        node_subs_uv_offset.location = -500,yTex


                        links.new(geometryNode.outputs[5], BIMaterial.inputs["Normal"])


                        #uv offset
                        links.new(geometryNode.outputs[4], node_add_uv_offset.inputs[0])
                        links.new(node_add_uv_offset.outputs[0], node_mapping.inputs["Vector"])
                        links.new(node_mapping.outputs[0], node_subs_uv_offset.inputs[0])
                        links.new(node_subs_uv_offset.outputs[0], node_texture.inputs["Vector"])


                else:

                    v = re.findall(r"[-+]?\d*\.\d+|\d+",value)



                    if( len(v) != 1):
                        print(v)
                        print(" parameter value"+value+" badly defined, expected 1 component!")
                        continue

                    if param == "Transparency":
                        shader.material.use_transparency = True
                        shader.material.alpha = float(v[0])
                    else:
                        shaderInput.default_value = float(v[0])

            elif inputType == "VECTOR":

                if "TextureNormal(" in value:

                    value = self.cleanSpaces(value[value.find("TextureNormal(")+14:value.rfind(")")])

                    node_normal = textures.get(value)

                    if  node_normal is None:

                        nbTextures = len( textures )

                        yTex = nbTextures * -300 + 300

                        image = self.getImage( value )



                        node_normal = nodes.new(type='ShaderNodeNormalMap')

                        node_normal.location = -250, yTex


                        node_texture = nodes.new(type='ShaderNodeTexImage')

                        node_texture.image = image

                        node_texture.location = -500, yTex

                        node_texture.color_space = "NONE"

                        node_uv = nodes.new(type='ShaderNodeUVMap')

                        node_uv.uv_map = "UVMap"

                        node_uv.location = -1200,yTex

                        node_mapping = nodes.new(type='ShaderNodeMapping')


                        node_mapping.scale = (scaleS,scaleT,1)

                        node_mapping.location = -900,yTex

                        textures[value] = node_normal

                        links.new(node_uv.outputs[0], node_mapping.inputs["Vector"])

                        links.new(node_mapping.outputs[0], node_texture.inputs["Vector"])

                        links.new(node_texture.outputs[0], node_normal.inputs[1])

                    links.new(node_normal.outputs[0], shaderInput)

                else:

                    v = re.findall(r"[-+]?\d*\.\d+|\d+",value)

                    if( len(v) != 3):
                        print(v)
                        print(" parameter value"+value+" badly defined, expected 3 component!")
                        continue

                    shaderInput.default_value[0] = float(v[0])
                    shaderInput.default_value[1] = float(v[1])
                    shaderInput.default_value[2] = float(v[2])

            else:
                print( "Parameter " + param + " has an unsupported input type " + shaderInput.type )

        if alphaConnected == False:

            links.new(BIMaterial.outputs["Alpha"], groupOutput.inputs["Alpha"], False)



    def createBIMaterials( self ):

        self.BItextures =  {}

        #get material definitions

        materialDefinitions = self.parseMaterialDefinitions()

        materialGroups = {}

        self.internalBImaterialGroups = {}

        for key in self.materials:

            material = self.materials[key]

            temp = material.name.split("#")

            frontMatId = int(temp[0]) + 1

            frontDef = materialDefinitions[frontMatId]

            newName = frontDef["Name"]



            backDef = None

            if self.back_materials:

                backMatId = int(temp[1]) + 1

                backDef = materialDefinitions[backMatId]

                newName += "/"

                newName += backDef["Name"]

            material.name = newName

            material.use_nodes = True

            nodes = material.node_tree.nodes

            #delete existing node and move output

            nodes.remove(nodes["Material"])

            nodes["Output"].location = (600,0)

            #add front material group

            textureNodes = {}

            frontShader = self.getMaterialGroupBI(frontMatId, frontDef, nodes, textureNodes)

            if self.internalBImaterialGroups[frontMatId].material.use_transparency == True:
                material.use_transparency = True
                material.use_cast_shadows = False
            #add texture to material if needed
            if self.BItextures.get(frontDef["Name"]):
                mtex = material.texture_slots.add()
                mtex.texture = self.BItextures.get(frontDef["Name"])

            frontShader.location = (0,150)

            if not self.back_materials:

                #link output

                material.node_tree.links.new(frontShader.outputs[0], nodes["Output"].inputs['Color'])

            else:

                #create back shader and mix them based on the geometry

                backShader = self.getMaterialGroupBI(backMatId, backDef, nodes, textureNodes)

                if self.internalBImaterialGroups[backMatId].material.use_transparency == True :
                    material.use_transparency = True
                    material.use_cast_shadows = False

                if self.BItextures.get(backDef["Name"]):
                    mtex = material.texture_slots.add()
                    mtex.texture = self.BItextures.get(backDef["Name"])

                #backShader = nodes.new('ShaderNodeGroup')

                #backShader.node_tree = bpy.data.node_groups [backDef["Type"]]

                backShader.location = (0,-150)

                #create geometry shader

                node_geometry = nodes.new('ShaderNodeGeometry')

                node_geometry.location = (0,500)

                #create mix shader

                node_backMix = nodes.new('ShaderNodeMixRGB')

                node_backMix.location = (350,0)

                #create mix shader for alpha

                node_backMix2 = nodes.new('ShaderNodeMixRGB')

                node_backMix2.location = (350,-250)

                #link

                material.node_tree.links.new(node_geometry.outputs[8], node_backMix.inputs[0])

                material.node_tree.links.new(frontShader.outputs[0], node_backMix.inputs[2])

                material.node_tree.links.new(backShader.outputs[0], node_backMix.inputs[1])

                material.node_tree.links.new(node_backMix.outputs[0], nodes["Output"].inputs['Color'])

                material.node_tree.links.new(node_geometry.outputs[8], node_backMix2.inputs[0])

                material.node_tree.links.new(frontShader.outputs[1], node_backMix2.inputs[2])

                material.node_tree.links.new(backShader.outputs[1], node_backMix2.inputs[1])

                material.node_tree.links.new(node_backMix2.outputs[0], nodes["Output"].inputs['Alpha'])


    def createCycleMaterials( self ):

        #get material definitions

        materialDefinitions = self.parseMaterialDefinitions()

        #create blendup standard material groups

        #self.createBlendUpAO()

        self.createBlendUpMonochrome()

        self.createBlendUpDiffuse()

        self.createBlendUpLight()

        self.createBlendUpGlass()

        self.createBlendUpGlossy()

        self.createBlendUpMixDiffuseGlossy()

        self.createBlendUpMixDiffuseGlossy2()

        self.createBlendUpFabric()

        #self.createBlendUpPBR()

        materialGroups = {}

        for key in self.materials:

            material = self.materials[key]

            temp = material.name.split("#")

            frontMatId = int(temp[0]) + 1

            frontDef = materialDefinitions[frontMatId]

            newName = frontDef["Name"]

            backDef = None

            if self.back_materials:

                backMatId = int(temp[1]) + 1

                backDef = materialDefinitions[backMatId]

                newName += "/"

                newName += backDef["Name"]

            material.name = newName

            material.use_nodes = True

            nodes = material.node_tree.nodes

            #delete existing node and move output

            nodes.remove(nodes["Diffuse BSDF"])

            nodes["Material Output"].location = (600,0)

            #add front material group

            frontShader = self.getMaterialGroup(frontMatId, frontDef, nodes)

            #frontShader = nodes.new('ShaderNodeGroup')

            #frontShader.node_tree = bpy.data.node_groups [frontDef["Type"]]

            #self.connectNodes(frontDef,frontShader,textureNodes, nodes, material.node_tree.links, True )

            frontShader.location = (0,150)

            if not self.back_materials:

                #link output

                material.node_tree.links.new(frontShader.outputs[0], nodes["Material Output"].inputs['Surface'])

            else:

                #create back shader and mix them based on the geometry

                backShader = self.getMaterialGroup(backMatId, backDef, nodes)

                #backShader = nodes.new('ShaderNodeGroup')

                #backShader.node_tree = bpy.data.node_groups [backDef["Type"]]

                backShader.location = (0,-150)

                #create geometry shader

                node_geometry = nodes.new('ShaderNodeNewGeometry')

                node_geometry.location = (0,500)

                #create mix shader

                node_backMix = nodes.new('ShaderNodeMixShader')

                node_backMix.location = (350,0)

                #link

                material.node_tree.links.new(node_geometry.outputs[6], node_backMix.inputs[0])

                material.node_tree.links.new(frontShader.outputs[0], node_backMix.inputs[1])

                material.node_tree.links.new(backShader.outputs[0], node_backMix.inputs[2])

                material.node_tree.links.new(node_backMix.outputs[0], nodes["Material Output"].inputs['Surface'])

                #self.connectNodes(frontDef,frontShader,textureNodes, nodes, material.node_tree.links, True )

                #self.connectNodes(backDef,backShader,textureNodes, nodes, material.node_tree.links, False )
