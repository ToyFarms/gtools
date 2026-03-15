#version 450 core

layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec2 in_texCoord;

layout (location = 2) in vec2 in_tilePos;
layout (location = 3) in vec2 in_tileScale;
layout (location = 4) in vec2 in_texCoords;
layout (location = 5) in float in_layer;
layout (location = 6) in float in_depth;

out vec2 texCoord;
flat out float layer;

uniform mat4 u_view_proj;
uniform sampler2DArray texArray;
uniform float u_tileSize;
uniform float u_rotation;
uniform float u_pixelScale;
uniform float u_layer_spread;
uniform float u_zOffset;

void main() {
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    mat2 rot = mat2(c, -s, s, c);
    vec2 rotated = rot * in_pos;

    vec2 worldPos = rotated * u_tileSize * in_tileScale + in_tilePos;
    float z = (in_depth + u_zOffset) * u_layer_spread;
    gl_Position = u_view_proj * vec4(worldPos.x, worldPos.y, z, 1.0);

    vec2 texSize = vec2(textureSize(texArray, 0).xy);
    vec2 uvStep = vec2(u_tileSize) / texSize;
    texCoord = vec2(
        mix(in_texCoords.x, in_texCoords.x + uvStep.x, in_texCoord.x),
        mix(in_texCoords.y, in_texCoords.y + uvStep.y, in_texCoord.y)
    );

    layer = in_layer;
}
