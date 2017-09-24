#ifndef EMAN_DOT_H
#define EMAN_DOT_H

#include "emdata.h"

using namespace EMAN;


__global__
void kernel_hello();

void cuda_hello();
float cpp_dot(EMData &obj1, EMData &obj2);

__global__
void kernel_dot(float *v1, float *v2, int N, float *);
float cuda_dot(EMData &obj1, EMData &obj2);
float thrust_inner_product(EMData &obj1, EMData &obj2);

#endif //EMAN_DOT_H
