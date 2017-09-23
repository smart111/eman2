#include "dot.h"

#include <stdio.h>
#include <vector>

using namespace std;

typedef vector<float> VF;

__global__
void kernel_hello() {
    printf("Hello! Idx: %d\n", threadIdx);
}

void cuda_hello() {
    kernel_hello<<<1,5>>>();
    cudaDeviceSynchronize();
}

float cpp_dot(EMData &obj1, EMData &obj2) {
    VF v1(obj1.get_data_as_vector());
    VF v2(obj2.get_data_as_vector());

    float sum = 0.0f;
    for(int i=0; i<v1.size(); ++i)
        sum += v1[i] * v2[i];

    return sum;
}
