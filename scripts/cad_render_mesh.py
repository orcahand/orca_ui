"""Tessellate CAD surfaces at an absolute millimetre tolerance with analytic normals."""
import numpy as np
import trimesh
from OCP.BRep import BRep_Tool
from OCP.BRepTools import BRepTools
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepLib import BRepLib_ToolTriangulatedShape
from OCP.TopLoc import TopLoc_Location
from OCP.TopAbs import TopAbs_REVERSED


def render_mesh(shape, tolerance=.06, angle=.15):
    BRepTools.Clean_s(shape.wrapped)
    BRepMesh_IncrementalMesh(shape.wrapped, tolerance, False, angle, True)
    vertices, normals, triangles = [], [], []
    for face in shape.Faces():
        location = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face.wrapped, location)
        if poly is None:
            continue
        BRepLib_ToolTriangulatedShape.ComputeNormals_s(face.wrapped, poly)
        transform = location.Transformation()
        reverse = face.wrapped.Orientation() == TopAbs_REVERSED
        offset, sign = len(vertices), -1 if reverse else 1
        for i in range(1, poly.NbNodes()+1):
            point = poly.Node(i).Transformed(transform)
            normal = poly.Normal(i).Transformed(transform)
            vertices.append([point.X(), point.Y(), point.Z()])
            normals.append([sign*normal.X(), sign*normal.Y(), sign*normal.Z()])
        for i in range(1, poly.NbTriangles()+1):
            triangle = poly.Triangle(i)
            a, b, c = [triangle.Value(j)+offset-1 for j in [1, 2, 3]]
            triangles.append([a, c, b] if reverse else [a, b, c])
    vertices, normals, triangles = np.array(vertices), np.array(normals), np.array(triangles)
    box = shape.BoundingBox()
    lo = np.array([box.xmin, box.ymin, box.zmin])-.1
    hi = np.array([box.xmax, box.ymax, box.zmax])+.1
    valid = np.all((vertices >= lo) & (vertices <= hi), axis=1)
    triangles = triangles[np.all(valid[triangles], axis=1)]
    used = np.unique(triangles)
    remap = np.full(len(vertices), -1)
    remap[used] = np.arange(len(used))
    return trimesh.Trimesh(vertices=vertices[used], faces=remap[triangles],
                           vertex_normals=normals[used], process=False)
