#include <stdio.h>

__global__
void kernel_hello() {
    printf("Hello! Idx: %d\n", threadIdx);
}

void cuda_hello() {
    kernel_hello<<<1,5>>>();
    cudaDeviceSynchronize();
}
