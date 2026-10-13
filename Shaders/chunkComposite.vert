#version 400 core

// Vertex attributes
layout (location = 0) in vec2 aPosition;  // Clip-space position [-1,1]
layout (location = 1) in vec2 aTexCoord;  // UV coordinates [0,1] in chunk texture

out vec2 TexCoord;

void main()
{
    gl_Position = vec4(aPosition, 0.0, 1.0);
    TexCoord = aTexCoord;
}
