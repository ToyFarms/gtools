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

uniform mat4 u_view_proj;
uniform sampler2DArray u_texture;
uniform float u_layer_spread;
uniform float u_tileSize;

vec4 unpackColor(uint c) {
    return vec4(
        float((c >> 24) & 0xFFu) / 255.0,  // R
        float((c >> 16) & 0xFFu) / 255.0,  // G
        float((c >>  8) & 0xFFu) / 255.0,  // B
        float((c >>  0) & 0xFFu) / 255.0   // A
    );
}

void main() {
    vec2 texSize = textureSize(u_texture, 0).xy;
    vec2 uvStep = vec2(u_tileSize / texSize.x, u_tileSize / texSize.y);

    baseTexCoord = in_baseUV + in_texCoord * uvStep;
    overlayTexCoord = in_overlayUV + in_texCoord * uvStep;

    baseTint = unpackColor(in_baseColor).rgb;
    overlayTint = unpackColor(in_overlayColor).rgb;

    vec2 worldPos = in_pos * u_tileSize + in_tilePos.xy;
    float z = in_tilePos.z * u_layer_spread;

    gl_Position = u_view_proj * vec4(worldPos.x, worldPos.y, z, 1.0);
    layer = in_layer;
}
