#version 450 core

out vec4 out_fragColor;
in vec4 color;
in vec2 uv;

void main() {

    float border = 0.05;
    float edge = min(min(uv.x, 1.0 - uv.x), min(uv.y, 1.0 - uv.y));
    float borderFactor = smoothstep(0.0, border, edge);

    vec3 baseColor = color.rgb;
    baseColor = mix(baseColor * 0.5, baseColor, borderFactor);
    baseColor += vec3(0.1) * (1.0 - uv.y) * borderFactor;

    out_fragColor = vec4(baseColor * color.a, color.a);
}
