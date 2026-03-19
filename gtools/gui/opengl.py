import ctypes
import logging
from pathlib import Path
from typing import Sequence, cast

import glfw
from OpenGL.GL import (
    GL_ARRAY_BUFFER,
    GL_BYTE,
    GL_COLOR_ATTACHMENT0,
    GL_COMPILE_STATUS,
    GL_DEPTH24_STENCIL8,
    GL_DEPTH_STENCIL_ATTACHMENT,
    GL_DYNAMIC_DRAW,
    GL_ELEMENT_ARRAY_BUFFER,
    GL_FALSE,
    GL_FLOAT,
    GL_FRAGMENT_SHADER,
    GL_FRAMEBUFFER,
    GL_FRAMEBUFFER_COMPLETE,
    GL_LINK_STATUS,
    GL_INT,
    GL_LINEAR,
    GL_READ_WRITE,
    GL_RENDERBUFFER,
    GL_RGBA,
    GL_RGBA8,
    GL_SHADER_STORAGE_BUFFER,
    GL_SHORT,
    GL_STATIC_DRAW,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TRIANGLES,
    GL_UNSIGNED_BYTE,
    GL_UNSIGNED_INT,
    GL_UNSIGNED_SHORT,
    GL_VERTEX_SHADER,
    glAttachShader,
    glBindBuffer,
    glBindBufferBase,
    glBindFramebuffer,
    glBindRenderbuffer,
    glBindTexture,
    glBindVertexArray,
    glBufferData,
    glBufferSubData,
    glCheckFramebufferStatus,
    glCompileShader,
    glCreateProgram,
    glCreateShader,
    glDeleteBuffers,
    glDeleteFramebuffers,
    glDeleteProgram,
    glDeleteRenderbuffers,
    glDeleteShader,
    glDeleteTextures,
    glDeleteVertexArrays,
    glDetachShader,
    glDrawArrays,
    glDrawArraysInstanced,
    glDrawElements,
    glDrawElementsInstanced,
    glEnableVertexAttribArray,
    glFramebufferRenderbuffer,
    glFramebufferTexture2D,
    glGenBuffers,
    glGenFramebuffers,
    glGenRenderbuffers,
    glGenTextures,
    glGenVertexArrays,
    glGetBufferSubData,
    glGetProgramInfoLog,
    glGetProgramiv,
    glGetShaderInfoLog,
    glGetShaderiv,
    glGetUniformLocation,
    glLinkProgram,
    glMapBuffer,
    glRenderbufferStorage,
    glShaderSource,
    glTexImage2D,
    glTexParameteri,
    glUniform1fv,
    glUniform1iv,
    glUniform1uiv,
    glUniform2fv,
    glUniform2iv,
    glUniform2uiv,
    glUniform3fv,
    glUniform3iv,
    glUniform3uiv,
    glUniform4fv,
    glUniform4iv,
    glUniform4uiv,
    glUniformMatrix2fv,
    glUniformMatrix3fv,
    glUniformMatrix4fv,
    glUnmapBuffer,
    glUseProgram,
    glVertexAttribDivisor,
    glVertexAttribIPointer,
    glVertexAttribPointer,
    glViewport,
)
import numpy as np
import numpy.typing as npt

logger = logging.getLogger("gui-opengl")


class Uniform:
    def __init__(self, loc: int) -> None:
        self.loc = loc

    def set_float(self, x: float) -> None:
        glUniform1fv(self.loc, 1, x)

    def set_int(self, x: int) -> None:
        glUniform1iv(self.loc, 1, x)

    def set_uint(self, x: int) -> None:
        glUniform1uiv(self.loc, 1, x)

    def set_vec2(self, x: npt.NDArray[np.float32] | ctypes.Array[ctypes.c_float]) -> None:
        if isinstance(x, np.ndarray):
            assert x.shape == (2,) and x.dtype == np.float32
        glUniform2fv(self.loc, 1, x)

    def set_vec3(self, x: npt.NDArray[np.float32] | ctypes.Array[ctypes.c_float]) -> None:
        if isinstance(x, np.ndarray):
            assert x.shape == (3,) and x.dtype == np.float32
        glUniform3fv(self.loc, 1, x)

    def set_vec4(self, x: npt.NDArray[np.float32] | ctypes.Array[ctypes.c_float]) -> None:
        if isinstance(x, np.ndarray):
            assert x.shape == (4,) and x.dtype == np.float32
        glUniform4fv(self.loc, 1, x)

    def set_ivec2(self, x: npt.NDArray[np.int32] | ctypes.Array[ctypes.c_int32]) -> None:
        if isinstance(x, np.ndarray):
            assert x.shape == (2,) and x.dtype == np.int32
        glUniform2iv(self.loc, 1, x)

    def set_ivec3(self, x: npt.NDArray[np.int32] | ctypes.Array[ctypes.c_int32]) -> None:
        if isinstance(x, np.ndarray):
            assert x.shape == (3,) and x.dtype == np.int32
        glUniform3iv(self.loc, 1, x)

    def set_ivec4(self, x: npt.NDArray[np.int32] | ctypes.Array[ctypes.c_int32]) -> None:
        if isinstance(x, np.ndarray):
            assert x.shape == (4,) and x.dtype == np.int32
        glUniform4iv(self.loc, 1, x)

    def set_uvec2(self, x: npt.NDArray[np.uint32] | ctypes.Array[ctypes.c_uint32]) -> None:
        if isinstance(x, np.ndarray):
            assert x.shape == (2,) and x.dtype == np.uint32
        glUniform2uiv(self.loc, 1, x)

    def set_uvec3(self, x: npt.NDArray[np.uint32] | ctypes.Array[ctypes.c_uint32]) -> None:
        if isinstance(x, np.ndarray):
            assert x.shape == (3,) and x.dtype == np.uint32
        glUniform3uiv(self.loc, 1, x)

    def set_uvec4(self, x: npt.NDArray[np.uint32] | ctypes.Array[ctypes.c_uint32]) -> None:
        if isinstance(x, np.ndarray):
            assert x.shape == (4,) and x.dtype == np.uint32
        glUniform4uiv(self.loc, 1, x)

    def set_float_array(self, x: npt.NDArray[np.float32]) -> None:
        assert x.dtype == np.float32 and x.ndim == 1
        glUniform1fv(self.loc, x.size, x)

    def set_int_array(self, x: npt.NDArray[np.int32]) -> None:
        assert x.dtype == np.int32 and x.ndim == 1
        glUniform1iv(self.loc, x.size, x)

    def set_uint_array(self, x: npt.NDArray[np.uint32]) -> None:
        assert x.dtype == np.uint32 and x.ndim == 1
        glUniform1uiv(self.loc, x.size, x)

    def set_mat2x2(self, x: npt.NDArray[np.float32] | ctypes.Array[ctypes.c_float]) -> None:
        if isinstance(x, np.ndarray):
            assert x.shape == (2, 2) and x.dtype == np.float32
        glUniformMatrix2fv(self.loc, 1, GL_FALSE, x)

    def set_mat3x3(self, x: npt.NDArray[np.float32] | ctypes.Array[ctypes.c_float]) -> None:
        if isinstance(x, np.ndarray):
            assert x.shape == (3, 3) and x.dtype == np.float32
        glUniformMatrix3fv(self.loc, 1, GL_FALSE, x)

    def set_mat4x4(self, x: npt.NDArray[np.float32] | ctypes.Array[ctypes.c_float]) -> None:
        if isinstance(x, np.ndarray):
            assert x.shape == (4, 4) and x.dtype == np.float32
        glUniformMatrix4fv(self.loc, 1, GL_FALSE, x)


class ShaderProgram:
    _SHADER: dict[str, "ShaderProgram"] = {}
    logger = logging.getLogger("shader-program")

    def __init__(self, vs_src: str, fs_src: str, id: str = "?") -> None:
        self._gl_id = self._link(vs_src, fs_src)
        self.id = id

    @staticmethod
    def get(id: str) -> "ShaderProgram":
        if id in ShaderProgram._SHADER:
            return ShaderProgram._SHADER[id]

        shader = ShaderProgram.from_file(id)
        ShaderProgram._SHADER[id] = shader

        return shader

    @classmethod
    def from_file(cls, vs_file: str | Path, fs_file: str | Path | None = None) -> "ShaderProgram":
        if vs_file and fs_file:
            return cls(Path(vs_file).read_text(), Path(fs_file).read_text(), id=Path(vs_file).with_suffix("").name)
        name = Path(vs_file).with_suffix("").name
        base = Path(vs_file).parent

        return cls.from_file(base / f"{name}.vert", base / f"{name}.frag")

    def use(self) -> None:
        glUseProgram(self._gl_id)

    def get_uniform(self, name: str) -> Uniform:
        id = glGetUniformLocation(self._gl_id, name)
        return Uniform(loc=id)

    @staticmethod
    def _compile(src: str, shader_type: int) -> int:
        shader = cast(int, glCreateShader(shader_type))
        glShaderSource(shader, src)
        glCompileShader(shader)
        if not glGetShaderiv(shader, GL_COMPILE_STATUS):
            raise RuntimeError(glGetShaderInfoLog(shader).decode(errors="ignore"))
        return shader

    @classmethod
    def _link(cls, vs_src: str, fs_src: str) -> int:
        vs = cls._compile(vs_src, GL_VERTEX_SHADER)
        fs = cls._compile(fs_src, GL_FRAGMENT_SHADER)
        prog = cast(int, glCreateProgram())
        glAttachShader(prog, vs)
        glAttachShader(prog, fs)
        glLinkProgram(prog)
        if not glGetProgramiv(prog, GL_LINK_STATUS):
            raise RuntimeError(glGetProgramInfoLog(prog).decode(errors="ignore"))
        for s in (vs, fs):
            glDetachShader(prog, s)
            glDeleteShader(s)
        return prog

    def delete(self) -> None:
        self.logger.debug(f"deleting shader {self.id} (id={self._gl_id})")
        if glfw.get_current_context():
            glDeleteProgram(self._gl_id)

    @staticmethod
    def delete_all() -> None:
        for key, shader in ShaderProgram._SHADER.items():
            shader.delete()


class Mesh:
    # fmt: off
    RECT_WITH_UV_VERTS = np.array([
        -0.5, -0.5, 0.0, 0.0,
        0.5, -0.5, 1.0, 0.0,
        0.5,  0.5, 1.0, 1.0,
        -0.5,  0.5, 0.0, 1.0,
    ], dtype=np.float32)
    RECT_WITH_UV_VERTS.setflags(write=False)
    # fmt: on
    RECT_INDICES = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint16)
    RECT_INDICES.setflags(write=False)

    def _setup_attribs(self, layout: Sequence[int | tuple[int, int]], base_loc: int, is_instance: bool = False) -> int:
        type_sizes = {
            GL_FLOAT: ctypes.sizeof(ctypes.c_float),
            GL_INT: ctypes.sizeof(ctypes.c_int),
            GL_UNSIGNED_INT: ctypes.sizeof(ctypes.c_uint),
            GL_BYTE: ctypes.sizeof(ctypes.c_byte),
            GL_UNSIGNED_BYTE: ctypes.sizeof(ctypes.c_ubyte),
            GL_SHORT: ctypes.sizeof(ctypes.c_short),
            GL_UNSIGNED_SHORT: ctypes.sizeof(ctypes.c_ushort),
        }
        integer_types = {GL_INT, GL_UNSIGNED_INT, GL_BYTE, GL_UNSIGNED_BYTE, GL_SHORT, GL_UNSIGNED_SHORT}

        parsed_layout = []
        stride = 0
        for item in layout:
            if isinstance(item, int):
                count, gl_type = item, GL_FLOAT
            else:
                count, gl_type = item
            size = type_sizes.get(gl_type, 4)
            parsed_layout.append((count, gl_type, size))
            stride += count * size

        offset = 0
        for i, (count, gl_type, size) in enumerate(parsed_layout):
            loc = base_loc + i
            glEnableVertexAttribArray(loc)
            if gl_type in integer_types:
                glVertexAttribIPointer(loc, count, gl_type, stride, ctypes.c_void_p(offset))
            else:
                glVertexAttribPointer(loc, count, gl_type, GL_FALSE, stride, ctypes.c_void_p(offset))

            if is_instance:
                glVertexAttribDivisor(loc, 1)
            offset += count * size

        return stride

    def __init__(
        self,
        vertices: npt.NDArray,
        layout: Sequence[int | tuple[int, int]],
        indices: npt.NDArray | None = None,
        usage: int = GL_STATIC_DRAW,
        instance_data: npt.NDArray | None = None,
        instance_layout: Sequence[int | tuple[int, int]] | None = None,
        instance_attrib_base: int | None = None,
    ) -> None:
        self._vao = glGenVertexArrays(1)
        glBindVertexArray(self._vao)

        self._vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices.tobytes(), usage)

        self._ebo = None
        self._index_count = 0
        self._index_type = None
        if indices is not None:
            if indices.dtype == np.uint16 or indices.dtype == np.int16:
                self._index_type = GL_UNSIGNED_SHORT
            else:
                indices = indices.astype(np.uint32)
                self._index_type = GL_UNSIGNED_INT

            self._ebo = glGenBuffers(1)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices.tobytes(), usage)
            self._index_count = int(indices.size)

        vertex_stride = self._setup_attribs(layout, 0)
        self._vertex_count = int(vertices.nbytes // vertex_stride)

        self._instance_vbo = None
        self._instance_count = 0
        if instance_data is not None and instance_layout is not None:
            if instance_attrib_base is None:
                raise ValueError("please supply instance_attrib_base (where the instance data begins)")

            self._instance_vbo = glGenBuffers(1)
            glBindBuffer(GL_ARRAY_BUFFER, self._instance_vbo)
            glBufferData(GL_ARRAY_BUFFER, instance_data.nbytes, instance_data.tobytes(), usage)

            instance_stride = self._setup_attribs(instance_layout, instance_attrib_base, is_instance=True)
            self._instance_count = int(instance_data.nbytes // instance_stride)

        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def draw(self, mode: int = GL_TRIANGLES) -> None:
        glBindVertexArray(self._vao)
        if self._index_count and self._index_type:
            glDrawElements(mode, self._index_count, self._index_type, None)
        else:
            glDrawArrays(mode, 0, self._vertex_count)
        glBindVertexArray(0)

    def draw_instanced(self, mode: int = GL_TRIANGLES) -> None:
        if self._instance_count == 0:
            raise RuntimeError("cannot draw instanced: no instance data")
        glBindVertexArray(self._vao)
        if self._index_count and self._index_type:
            glDrawElementsInstanced(mode, self._index_count, self._index_type, None, self._instance_count)
        else:
            glDrawArraysInstanced(mode, 0, self._vertex_count, self._instance_count)
        glBindVertexArray(0)

    def delete(self) -> None:
        glDeleteBuffers(1, [self._vbo])
        glDeleteVertexArrays(1, [self._vao])
        if self._ebo:
            glDeleteBuffers(1, [self._ebo])
        if self._instance_vbo:
            glDeleteBuffers(1, [self._instance_vbo])


class Framebuffer:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.fbo = glGenFramebuffers(1)
        self.color_tex = glGenTextures(1)
        self.rbo = glGenRenderbuffers(1)
        self._create_attachments()

    def _create_attachments(self) -> None:
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glBindTexture(GL_TEXTURE_2D, self.color_tex)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, self.width, self.height, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, self.color_tex, 0)
        glBindRenderbuffer(GL_RENDERBUFFER, self.rbo)
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8, self.width, self.height)
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, self.rbo)
        if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("FBO not complete")
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def resize(self, width: int, height: int) -> None:
        if width == self.width and height == self.height:
            return
        self.width = width
        self.height = height
        self._create_attachments()

    def bind(self) -> None:
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glViewport(0, 0, self.width, self.height)

    def unbind(self) -> None:
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def delete(self) -> None:
        glDeleteFramebuffers(1, [self.fbo])
        glDeleteTextures(1, [self.color_tex])
        glDeleteRenderbuffers(1, [self.rbo])


class SSBO:
    def __init__(
        self,
        binding: int,
        data: npt.NDArray | None = None,
        size: int | None = None,
        usage: int = GL_DYNAMIC_DRAW,
    ) -> None:
        if data is None and size is None:
            raise ValueError("supply either data or size")

        self.binding = binding
        self._ssbo = glGenBuffers(1)

        glBindBuffer(GL_SHADER_STORAGE_BUFFER, self._ssbo)
        if data is not None:
            self._size = data.nbytes
            glBufferData(GL_SHADER_STORAGE_BUFFER, self._size, data.tobytes(), usage)
        else:
            self._size = cast(int, size)
            glBufferData(GL_SHADER_STORAGE_BUFFER, self._size, None, usage)
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0)

    def bind(self) -> None:
        glBindBufferBase(GL_SHADER_STORAGE_BUFFER, self.binding, self._ssbo)

    def unbind(self) -> None:
        glBindBufferBase(GL_SHADER_STORAGE_BUFFER, self.binding, 0)

    def upload(self, data: npt.NDArray, offset: int = 0) -> None:
        if offset + data.nbytes > self._size:
            raise ValueError(f"upload out of range: offset={offset} data={data.nbytes}B buffer={self._size}B")

        glBindBuffer(GL_SHADER_STORAGE_BUFFER, self._ssbo)
        glBufferSubData(GL_SHADER_STORAGE_BUFFER, offset, data.nbytes, data.tobytes())
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0)

    def download(self, dtype: npt.DTypeLike, offset: int = 0, size: int | None = None) -> npt.NDArray:
        byte_count = (self._size - offset) if size is None else size
        if offset + byte_count > self._size:
            raise ValueError(f"download out of range: offset={offset} size={byte_count}B buffer={self._size}B")

        buf = np.empty(byte_count, dtype=np.uint8)
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, self._ssbo)
        glGetBufferSubData(GL_SHADER_STORAGE_BUFFER, offset, byte_count, buf)
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0)
        return buf.view(dtype)

    def map(self, access: int = GL_READ_WRITE) -> memoryview:
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, self._ssbo)
        ptr = glMapBuffer(GL_SHADER_STORAGE_BUFFER, access)

        return (ctypes.c_char * self._size).from_address(ptr)  # type: ignore[return-value]

    def unmap(self) -> None:
        glUnmapBuffer(GL_SHADER_STORAGE_BUFFER)
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0)

    @property
    def size(self) -> int:
        return self._size

    def delete(self) -> None:
        glDeleteBuffers(1, [self._ssbo])
