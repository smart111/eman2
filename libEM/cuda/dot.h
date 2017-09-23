#ifndef EMAN_DOT_H
#define EMAN_DOT_H

#include "emdata.h"

using namespace EMAN;


__global__
void kernel_hello();

void cuda_hello();
float cpp_dot(EMData &obj1, EMData &obj2);

#endif //EMAN_DOT_H
