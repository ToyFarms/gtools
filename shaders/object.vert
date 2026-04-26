#version 450 core

layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec2 in_texCoord;

layout (location = 2) in vec2 in_tilePos;
layout (location = 3) in vec2 in_tileScale;
layout (location = 4) in vec2 in_texCoords;
layout (location = 5) in float in_layer;
layout (location = 6) in float in_depth;
layout (location = 7) in uint in_tint;

out vec2 texCoord;
flat out float layer;
out vec4 tint;

uniform mat4 u_mvp;
uniform sampler2DArray texArray;
uniform float u_tileSize;
uniform float u_rotation;
uniform float u_zOffset;


vec4 unpackColor(uint c) {
    return vec4(
        float((c >> 24) & 0xFFu) / 255.0,  // R
        float((c >> 16) & 0xFFu) / 255.0,  // G
        float((c >>  8) & 0xFFu) / 255.0,  // B
        float((c >>  0) & 0xFFu) / 255.0   // A
    );
}

void main() {
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    mat2 rot = mat2(c, -s, s, c);
    vec2 rotated = rot * in_pos;

    vec2 worldPos = rotated * u_tileSize * in_tileScale + in_tilePos;
    gl_Position = u_mvp * vec4(worldPos, in_depth + u_zOffset, 1.0);

    vec2 texSize = textureSize(texArray, 0).xy;
    vec2 uvStep = vec2(u_tileSize) / texSize;
    texCoord = vec2(
        mix(in_texCoords.x, in_texCoords.x + uvStep.x, in_texCoord.x),
        mix(in_texCoords.y, in_texCoords.y + uvStep.y, in_texCoord.y)
    );
    layer = in_layer;
    tint = unpackColor(in_tint);
}
