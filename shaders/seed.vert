#version 450 core

layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec2 in_texCoord;

layout (location = 2) in vec3 in_tilePos;
layout (location = 3) in uint in_baseColor;
layout (location = 4) in uint in_overlayColor;
layout (location = 5) in vec2 in_baseUV;
layout (location = 6) in vec2 in_overlayUV;
layout (location = 7) in float in_layer;

out vec2 baseTexCoord;
out vec2 overlayTexCoord;
out vec3 baseTint;
out vec3 overlayTint;
flat out float layer;

uniform mat4 u_mvp;
uniform sampler2DArray u_texture;
uniform float u_tileSize;

vec3 unpackColor(uint c) {
    return vec3(
        float((c >> 16) & 0xFFu) / 255.0,
        float((c >> 8) & 0xFFu) / 255.0,
        float(c & 0xFFu) / 255.0
    );
}

void main() {
    vec2 texSize = textureSize(u_texture, 0).xy;
    vec2 uvStep = vec2(u_tileSize / texSize.x, u_tileSize / texSize.y);

    baseTexCoord = in_baseUV + in_texCoord * uvStep;
    overlayTexCoord = in_overlayUV + in_texCoord * uvStep;

    baseTint = unpackColor(in_baseColor);
    overlayTint = unpackColor(in_overlayColor);

    vec2 worldPos = in_pos * u_tileSize + in_tilePos.xy;
    gl_Position = u_mvp * vec4(worldPos, in_tilePos.z, 1.0);
    layer = in_layer;
}
