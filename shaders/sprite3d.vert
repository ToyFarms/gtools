#version 450 core

// 3D variant of sprite.vert: the per-instance depth is spread apart on the
// z axis so the layer stack separates in perspective.

layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec2 in_texCoord;

layout (location = 2) in vec2 in_spritePos;
layout (location = 3) in vec2 in_spriteSize;
layout (location = 4) in vec4 in_texCoords;
layout (location = 5) in float in_texLayer;
layout (location = 6) in float in_depth;
layout (location = 7) in float in_paintIndex;
layout (location = 8) in uint in_tint;
layout (location = 9) in float in_opacity;

out vec2 texCoord;
flat out float texLayer;
flat out float paintIndex;
flat out uint tint;
flat out float opacity;

uniform mat4 u_view_proj;
uniform float u_layer_spread;

void main() {
    vec2 worldPos = in_spritePos + in_pos * in_spriteSize;
    gl_Position = u_view_proj * vec4(worldPos.x, worldPos.y, in_depth * u_layer_spread, 1.0);

    texCoord = vec2(
        mix(in_texCoords.x, in_texCoords.z, in_texCoord.x),
        mix(in_texCoords.y, in_texCoords.w, in_texCoord.y)
    );
    texLayer = in_texLayer;
    paintIndex = in_paintIndex;
    tint = in_tint;
    opacity = in_opacity;
}
