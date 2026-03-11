#version 450 core

layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec2 in_texCoord;

layout (location = 3) in vec2 in_tilePos;
layout (location = 4) in vec4 in_texCoords;
layout (location = 5) in float in_layer;

out vec2 texCoord;
flat out float layer;

uniform mat4 u_mvp;
uniform float u_layer;

const float TILE_SIZE = 32.0f;

void main() {
    vec2 worldPos = in_pos * TILE_SIZE + in_tilePos;
    gl_Position = u_mvp * vec4(worldPos, u_layer, 1.0);

    texCoord = vec2(
        mix(in_texCoords.x, in_texCoords.z, in_texCoord.x),
        mix(in_texCoords.y, in_texCoords.w, in_texCoord.y)
    );
    layer = in_layer;
}
