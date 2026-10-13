#version 400 core

// Integer output format required for FBO
layout (location = 0) out vec4 FragColor;

void main()
{
    // Output 1 in red channel. This color will be added to
    // current framebuffer value thanks to additive blending.
    FragColor = vec4(1.0, 0.0, 0.0, 1.0);
}