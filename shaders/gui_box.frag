#version 450 core

out vec4 out_fragColor;
in vec2 texCoord;

uniform sampler2DArray u_texture;
uniform float u_layer;
uniform vec2 u_size;
uniform vec2 u_texRes;

float borderMap(float t, float s, float r) {
    float border_px = (r - 1.0) / 2.0;
    float px = t * s;
    if (px < border_px)
        return px / r;
    else if (px > s - border_px)
        return (r - border_px + (px - (s - border_px))) / r;
    else
        return border_px / r;
}

void main() {
    vec2 uv = vec2(
        borderMap(texCoord.x, u_size.x, u_texRes.x),
        borderMap(texCoord.y, u_size.y, u_texRes.y)
    );

    out_fragColor = texture(u_texture, vec3(uv, u_layer));
    if (out_fragColor.a < 0.01) discard;
    out_fragColor.a = 1.0;
}
