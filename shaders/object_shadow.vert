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
out vec4 tint;

uniform mat4 u_mvp;
uniform sampler2DArray texArray;
uniform float u_tileSize;
uniform vec2 u_shadowOffset;
uniform float u_zOffset;

void main() {
    vec2 worldPos = in_pos * u_tileSize * in_tileScale + in_tilePos + u_shadowOffset;
    gl_Position = u_mvp * vec4(worldPos, in_depth + u_zOffset, 1.0);

    vec2 texSize = vec2(textureSize(texArray, 0).xy);
    vec2 uvStep  = vec2(u_tileSize) / texSize;
    texCoord = vec2(
        mix(in_texCoords.x, in_texCoords.x + uvStep.x, in_texCoord.x),
        mix(in_texCoords.y, in_texCoords.y + uvStep.y, in_texCoord.y)
    );
    layer = in_layer;
    tint = vec4(1.0);
}

