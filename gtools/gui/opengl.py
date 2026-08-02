import ctypes
import logging
from pathlib import Path
import threading
from typing import Any, Sequence, cast
from watchdog.events import DirModifiedEvent, FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from OpenGL.GL import (
    GL_ALREADY_SIGNALED,
    GL_ARRAY_BUFFER,
    GL_BYTE,
    GL_COLOR_ATTACHMENT0,
    GL_COMPILE_STATUS,
    GL_COMPUTE_SHADER,
    GL_CONDITION_SATISFIED,
    GL_COPY_READ_BUFFER,
    GL_DEPTH24_STENCIL8,
    GL_DEPTH_STENCIL_ATTACHMENT,
    GL_DYNAMIC_DRAW,
    GL_ELEMENT_ARRAY_BUFFER,
    GL_FALSE,
    GL_FLOAT,
    GL_FRAGMENT_SHADER,
    GL_FRAMEBUFFER,
    GL_FRAMEBUFFER_COMPLETE,
    GL_GEOMETRY_SHADER,
    GL_LINK_STATUS,
    GL_INT,
    GL_LINEAR,
    GL_MAP_COHERENT_BIT,
    GL_MAP_PERSISTENT_BIT,
    GL_MAP_READ_BIT,
    GL_PIXEL_PACK_BUFFER,
    GL_READ_WRITE,
    GL_RENDERBUFFER,
    GL_RGBA,
    GL_RGBA8,
    GL_SHADER_STORAGE_BUFFER,
    GL_SHORT,
    GL_STATIC_DRAW,
    GL_SYNC_FLUSH_COMMANDS_BIT,
    GL_SYNC_GPU_COMMANDS_COMPLETE,
    GL_TESS_CONTROL_SHADER,
    GL_TESS_EVALUATION_SHADER,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TIMEOUT_IGNORED,
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
    glBufferStorage,
    glBufferSubData,
    glCheckFramebufferStatus,
    glClientWaitSync,
    glCompileShader,
    glCopyBufferSubData,
    glCreateProgram,
    glCreateShader,
    glDeleteBuffers,
    glDeleteFramebuffers,
    glDeleteProgram,
    glDeleteRenderbuffers,
    glDeleteShader,
    glDeleteSync,
    glDeleteTextures,
    glDeleteVertexArrays,
    glDetachShader,
    glDrawArrays,
    glDrawArraysInstanced,
    glDrawElements,
    glDrawElementsInstanced,
    glEnableVertexAttribArray,
    glFenceSync,
    glFramebufferRenderbuffer,
    glFramebufferTexture2D,
    glGenBuffers,
    glGenFramebuffers,
    glGenRenderbuffers,
    glGenTextures,
    glGenVertexArrays,
    glGetProgramInfoLog,
    glGetProgramiv,
    glGetShaderInfoLog,
    glGetShaderiv,
    glGetUniformLocation,
    glLinkProgram,
    glMapBuffer,
    glMapBufferRange,
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


def _build_ext_map() -> dict[str, int]:
    m: dict[str, int] = {
        ".vert": GL_VERTEX_SHADER,
        ".frag": GL_FRAGMENT_SHADER,
    }
    try:
        m[".geom"] = GL_GEOMETRY_SHADER
    except ImportError:
        pass
    try:
        m[".comp"] = GL_COMPUTE_SHADER
    except ImportError:
        pass
    try:
        m[".tesc"] = GL_TESS_CONTROL_SHADER
        m[".tese"] = GL_TESS_EVALUATION_SHADER
    except ImportError:
        pass
    return m


class _ReloadHandler(FileSystemEventHandler):
    _DEBOUNCE_S = 0.15

    def __init__(self) -> None:
        self._map: dict[Path, list[ShaderProgram]] = {}
        self._timers: dict[Path, threading.Timer] = {}
        self._lock = threading.Lock()

    def register(self, path: Path, shader: "ShaderProgram") -> None:
        path = path.resolve()
        with self._lock:
            self._map.setdefault(path, []).append(shader)

    def clear(self) -> None:
        with self._lock:
            for t in self._timers.values():
                t.cancel()

            self._timers.clear()
            self._map.clear()

    def on_modified(self, event: DirModifiedEvent | FileModifiedEvent) -> None:
        if isinstance(event, DirModifiedEvent):
            return

        path = Path(event.src_path if isinstance(event.src_path, str) else event.src_path.decode()).resolve()
        with self._lock:
            shaders = list(self._map.get(path, []))
            if not shaders:
                return

            if path in self._timers:
                self._timers[path].cancel()

            timer = threading.Timer(self._DEBOUNCE_S, self._fire, args=(path, shaders))
            self._timers[path] = timer

        timer.start()

    def _fire(self, path: Path, shaders: list["ShaderProgram"]) -> None:
        with self._lock:
            self._timers.pop(path, None)

        for shader in shaders:
            shader._mark_dirty()


_SourceEntry = tuple[int, Path | None, str | None]


class ShaderProgram:
    _registry: dict[str, "ShaderProgram"] = {}
    _observer: Any = None
    _handler: _ReloadHandler = _ReloadHandler()
    _watched_dirs: set[Path] = set()

    logger = logging.getLogger("shader-program")

    def __init__(self, key: str, gl_id: int, sources: list[_SourceEntry]) -> None:
        self._key = key
        self._gl_id = gl_id
        self._sources = sources
        self._dirty = False
        self._lock = threading.Lock()

    @classmethod
    def get(cls, path: str | Path) -> "ShaderProgram":
        base = Path(path).resolve()
        key = str(base)
        if key in cls._registry:
            return cls._registry[key]

        ext_map = _build_ext_map()
        pairs: list[tuple[int, Path]] = [(shader_type, base.with_suffix(ext)) for ext, shader_type in ext_map.items() if base.with_suffix(ext).exists()]
        if not pairs:
            raise FileNotFoundError(f"no shader stage files found for base path '{base}'. expected at least one of: " + ", ".join(f"*{e}" for e in ext_map))

        return cls._load_from_file_pairs(key, pairs)

    @classmethod
    def from_files(cls, *paths: str | Path) -> "ShaderProgram":
        ext_map = _build_ext_map()
        pairs: list[tuple[int, Path]] = []
        for p in paths:
            path = Path(p).resolve()
            ext = path.suffix.lower()
            if ext not in ext_map:
                raise ValueError(f"cannot infer shader type from extension '{ext}' (file: '{path}'). known extensions: {', '.join(ext_map)}")

            pairs.append((ext_map[ext], path))

        key = "|".join(str(p) for _, p in pairs)
        if key in cls._registry:
            return cls._registry[key]

        return cls._load_from_file_pairs(key, pairs)

    @classmethod
    def from_strings(cls, key: str, *type_src_pairs: tuple[int, str]) -> "ShaderProgram":
        if key in cls._registry:
            return cls._registry[key]

        gl_id = cls._link([(t, src) for t, src in type_src_pairs])
        sources: list[_SourceEntry] = [(t, None, src) for t, src in type_src_pairs]
        shader = cls(key, gl_id, sources)
        cls._registry[key] = shader
        cls.logger.debug(f"shader '{key}' compiled from strings")

        return shader

    def use(self) -> None:
        if self._dirty:
            self._recompile()

        with self._lock:
            glUseProgram(self._gl_id)

    def get_uniform(self, name: str) -> Uniform:
        with self._lock:
            loc = cast(int, glGetUniformLocation(self._gl_id, name))

        return Uniform(loc=loc)

    def delete(self) -> None:
        self.logger.debug(f"deleting shader '{self._key}' (gl_id={self._gl_id})")
        with self._lock:
            try:
                glDeleteProgram(self._gl_id)
            except Exception:
                self.logger.debug(f"ignored glDeleteProgram failure for '{self._key}'")
        ShaderProgram._registry.pop(self._key, None)

    @classmethod
    def delete_all(cls) -> None:
        for shader in list(cls._registry.values()):
            try:
                shader.delete()
            except Exception:
                cls.logger.debug(f"ignored delete_all failure for shader '{shader._key}'")

        cls._registry.clear()
        cls._handler.clear()
        cls._watched_dirs.clear()

        if cls._observer is not None:
            cls._observer.stop()
            cls._observer.join()
            cls._observer = None

    @classmethod
    def _load_from_file_pairs(cls, key: str, pairs: list[tuple[int, Path]]) -> "ShaderProgram":
        raw = [(t, p.read_text()) for t, p in pairs]
        gl_id = cls._link(raw)
        sources: list[_SourceEntry] = [(t, p, None) for t, p in pairs]
        shader = cls(key, gl_id, sources)
        cls._registry[key] = shader

        for _, path in pairs:
            cls._handler.register(path, shader)
            cls._ensure_watched(path.parent)

        cls.logger.debug(f"Shader '{key}' compiled from " + ", ".join(str(p) for _, p in pairs))
        return shader

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.logger.debug(f"shader '{self._key}' source changed on disk")

    def _recompile(self) -> None:
        self._dirty = False
        try:
            raw: list[tuple[int, str]] = []
            for shader_type, path, src_str in self._sources:
                src = path.read_text() if path is not None else src_str
                assert src is not None
                raw.append((shader_type, src))

            new_gl_id = self._link(raw)

            with self._lock:
                old_id = self._gl_id
                self._gl_id = new_gl_id

            glDeleteProgram(old_id)
            self.logger.info(f"shader '{self._key}' recompiled successfully")

        except Exception as exc:
            self.logger.error(f"shader '{self._key}' recompilation failed: {exc}")

    @classmethod
    def _ensure_watched(cls, directory: Path) -> None:
        if directory in cls._watched_dirs:
            return

        if cls._observer is None:
            cls._observer = Observer()
            cls._observer.start()

        cls._observer.schedule(cls._handler, str(directory), recursive=False)
        cls._watched_dirs.add(directory)

    @staticmethod
    def _compile(src: str, shader_type: int) -> int:
        shader = cast(int, glCreateShader(shader_type))
        glShaderSource(shader, src)
        glCompileShader(shader)

        if not glGetShaderiv(shader, GL_COMPILE_STATUS):
            log = glGetShaderInfoLog(shader).decode(errors="replace")
            glDeleteShader(shader)

            raise RuntimeError(f"shader compilation failed: {log}")

        return shader

    @classmethod
    def _link(cls, sources: list[tuple[int, str]]) -> int:
        compiled: list[int] = []
        try:
            for shader_type, src in sources:
                compiled.append(cls._compile(src, shader_type))

            prog = cast(int, glCreateProgram())
            for s in compiled:
                glAttachShader(prog, s)
            glLinkProgram(prog)

            if not glGetProgramiv(prog, GL_LINK_STATUS):
                log = glGetProgramInfoLog(prog).decode(errors="replace")
                glDeleteProgram(prog)

                raise RuntimeError(f"shader link failed: {log}")

            for s in compiled:
                glDetachShader(prog, s)

            return prog
        finally:
            for s in compiled:
                glDeleteShader(s)


class Mesh:
    # fmt: off
    RECT_WITH_UV_VERTS = np.array([
        -0.5, -0.5, 0.0, 0.0,
        0.5, -0.5, 1.0, 0.0,
        0.5,  0.5, 1.0, 1.0,
        -0.5,  0.5, 0.0, 1.0,
    ], dtype=np.float32)
    RECT_WITH_UV_VERTS.setflags(write=False)
    RECT_VERTS = np.array([
        -0.5, -0.5,
        0.5,  -0.5,
        0.5,  0.5,
        -0.5, 0.5,
    ], dtype=np.float32)
    RECT_VERTS.setflags(write=False)
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
            return

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


class DownloadRequest:
    def is_ready(self) -> bool:
        raise NotImplementedError

    def result(self) -> np.ndarray:
        raise NotImplementedError

    def cancel(self) -> None:
        raise NotImplementedError


class PersistentReadbackRing:
    _shared: "PersistentReadbackRing | None" = None

    def __init__(self, slot_size: int, slot_count: int = 4) -> None:
        if slot_size <= 0:
            raise ValueError("slot_size must be > 0")
        if slot_count <= 0:
            raise ValueError("slot_count must be > 0")

        self.slot_size = int(slot_size)
        self.slot_count = int(slot_count)
        self._byte_size = self.slot_size * self.slot_count

        self._pbo = glGenBuffers(1)
        glBindBuffer(GL_PIXEL_PACK_BUFFER, self._pbo)

        flags = GL_MAP_READ_BIT | GL_MAP_PERSISTENT_BIT | GL_MAP_COHERENT_BIT  # pyright: ignore[reportOperatorIssue]
        glBufferStorage(GL_PIXEL_PACK_BUFFER, self._byte_size, None, flags)
        ptr = glMapBufferRange(GL_PIXEL_PACK_BUFFER, 0, self._byte_size, flags)
        glBindBuffer(GL_PIXEL_PACK_BUFFER, 0)

        if not ptr:
            glDeleteBuffers(1, [self._pbo])
            raise RuntimeError("glMapBufferRange failed for persistent readback ring")

        self._base_addr = int(ptr)
        self._fences: list[int | None] = [None] * self.slot_count
        self._next_slot = 0

    @classmethod
    def shared(cls, *, min_slot_size: int, slot_count: int = 4) -> "PersistentReadbackRing":
        if cls._shared is None or cls._shared.slot_count != slot_count or cls._shared.slot_size < min_slot_size:
            if cls._shared is not None:
                try:
                    cls._shared.delete()
                except Exception:
                    pass
            cls._shared = PersistentReadbackRing(slot_size=min_slot_size, slot_count=slot_count)

        return cls._shared

    def delete(self) -> None:
        for i in range(self.slot_count):
            fence = self._fences[i]
            if fence is not None:
                glDeleteSync(fence)
                self._fences[i] = None
        glBindBuffer(GL_PIXEL_PACK_BUFFER, self._pbo)
        try:
            glUnmapBuffer(GL_PIXEL_PACK_BUFFER)
        except Exception:
            pass
        glBindBuffer(GL_PIXEL_PACK_BUFFER, 0)
        glDeleteBuffers(1, [self._pbo])

    def __del__(self) -> None:
        try:
            self.delete()
        except Exception:
            pass

    def _try_reclaim(self, idx: int) -> bool:
        fence = self._fences[idx]
        if fence is None:
            return True

        status = glClientWaitSync(fence, 0, 0)
        if status in (GL_ALREADY_SIGNALED, GL_CONDITION_SATISFIED):
            glDeleteSync(fence)
            self._fences[idx] = None
            return True

        return False

    def acquire_slot(self) -> int | None:
        for _ in range(self.slot_count):
            idx = self._next_slot
            self._next_slot = (self._next_slot + 1) % self.slot_count
            if self._try_reclaim(idx):
                return idx

        return None

    def slot_offset(self, idx: int) -> int:
        return idx * self.slot_size

    def fence_for(self, idx: int) -> int | None:
        return self._fences[idx]

    def set_fence(self, idx: int, fence: int) -> None:
        self._fences[idx] = fence

    def release(self, idx: int) -> None:
        fence = self._fences[idx]
        if fence is not None:
            glDeleteSync(fence)
        self._fences[idx] = None

    def base_addr(self) -> int:
        return self._base_addr

    def pbo_id(self) -> int:
        return self._pbo


class _RingDownloadRequest(DownloadRequest):
    def __init__(self, ring: PersistentReadbackRing, slot: int, fence: int, out: np.ndarray, byte_count: int) -> None:
        self._ring = ring
        self._slot = slot
        self._fence = fence
        self._out = out
        self._byte_count = byte_count
        self._resolved = False

    def is_ready(self) -> bool:
        if self._resolved:
            return True
        status = glClientWaitSync(self._fence, 0, 0)
        return status in (GL_ALREADY_SIGNALED, GL_CONDITION_SATISFIED)

    def result(self) -> np.ndarray:
        if self._resolved:
            return self._out

        glClientWaitSync(self._fence, GL_SYNC_FLUSH_COMMANDS_BIT, GL_TIMEOUT_IGNORED)
        self._cleanup_sync()

        src_addr = self._ring.base_addr() + self._ring.slot_offset(self._slot)
        ctypes.memmove(self._out.ctypes.data, src_addr, self._byte_count)
        self._resolved = True
        return self._out

    def cancel(self) -> None:
        if self._resolved:
            return
        self._cleanup_sync()
        self._resolved = True

    def _cleanup_sync(self) -> None:
        self._fence = None
        try:
            self._ring.release(self._slot)
        except Exception:
            pass

    def __del__(self) -> None:
        try:
            self.cancel()
        except Exception:
            pass


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

    def download(self, out: np.ndarray, offset: int = 0, size: int | None = None) -> None:
        byte_count = out.nbytes if size is None else size
        if offset + byte_count > self._size:
            raise ValueError(f"download out of range: offset={offset} size={byte_count}B buffer={self._size}B")

        glBindBuffer(GL_SHADER_STORAGE_BUFFER, self._ssbo)
        ptr = glMapBufferRange(GL_SHADER_STORAGE_BUFFER, offset, byte_count, GL_MAP_READ_BIT)
        if not ptr:
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0)
            raise RuntimeError("glMapBufferRange failed")

        try:
            ctypes.memmove(out.ctypes.data, int(ptr), byte_count)
        finally:
            glUnmapBuffer(GL_SHADER_STORAGE_BUFFER)
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0)

    def begin_download(self, out: np.ndarray, offset: int = 0, size: int | None = None) -> DownloadRequest:
        byte_count = out.nbytes if size is None else size
        if offset + byte_count > self._size:
            raise ValueError(f"begin_download out of range: offset={offset} size={byte_count}B buffer={self._size}B")

        ring = PersistentReadbackRing.shared(min_slot_size=byte_count, slot_count=4)
        slot = ring.acquire_slot()
        if slot is None:
            raise RuntimeError("failed to acquire a slot")

        glBindBuffer(GL_COPY_READ_BUFFER, self._ssbo)
        glBindBuffer(GL_PIXEL_PACK_BUFFER, ring.pbo_id())
        glCopyBufferSubData(GL_COPY_READ_BUFFER, GL_PIXEL_PACK_BUFFER, offset, ring.slot_offset(slot), byte_count)
        glBindBuffer(GL_COPY_READ_BUFFER, 0)
        glBindBuffer(GL_PIXEL_PACK_BUFFER, 0)

        fence: int = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0)  # pyright: ignore[reportAssignmentType]
        ring.set_fence(slot, fence)

        return _RingDownloadRequest(ring, slot, fence, out, byte_count)

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
