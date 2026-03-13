#version 450 core

layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec2 in_texCoord;

layout (location = 3) in vec2 in_tilePos;
layout (location = 4) in vec4 in_texCoords;
layout (location = 5) in float in_layer;
layout (location = 6) in float in_paintIndex;

out vec2 texCoord;
flat out float layer;
flat out float paintIndex;

uniform mat4 u_view_proj;
uniform float u_layer;
uniform float u_layer_spread;

const float TILE_SIZE = 32.0f;

void main() {
    vec2 worldPos = in_pos * TILE_SIZE + in_tilePos;
    float z = u_layer * u_layer_spread;
    gl_Position = u_view_proj * vec4(worldPos.x, worldPos.y, z, 1.0);

    texCoord = vec2(
        mix(in_texCoords.x, in_texCoords.z, in_texCoord.x),
        mix(in_texCoords.y, in_texCoords.w, in_texCoord.y)
    );
    layer = in_layer;
    paintIndex = in_paintIndex;
}
