#include "dot.h"

#include <stdio.h>
#include <vector>

#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/inner_product.h>
#include <thrust/iterator/zip_iterator.h>
#include <thrust/tuple.h>
#include "cublas_v2.h"

#define THREADSPERBLOCK 1024

using namespace std;

typedef vector<float> VF;

typedef thrust::host_vector<float> HV;
typedef thrust::device_vector<float> DV;

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

__global__
void kernel_dot(float *v1, float *v2, int N, float *sum) {
    __shared__ float cc[THREADSPERBLOCK];
    int i = blockDim.x * blockIdx.x + threadIdx.x;
    if(i<N) {
        float mm = v1[i] * v2[i];
        cc[threadIdx.x] = v1[i] * v2[i];
//        printf(" %d %f %f %d %d %d\n", i, ss, *sum, blockDim.x, blockIdx.x, threadIdx.x);
//        atomicAdd(sum, mm);
//        *su += ss;
//        printf("sum= %f", *sum);
    }
    __syncthreads();

    for(int stride = blockDim.x/2; threadIdx.x < stride && stride>0; stride /=2) {
        cc[threadIdx.x] += cc[threadIdx.x + stride];
        __syncthreads();
    }
    
    if(threadIdx.x == 0)
        sum[blockIdx.x] = cc[0];
}

float cuda_dot(EMData &obj1, EMData &obj2) {
    float * h_v1 = obj1.get_data();
    float * h_v2 = obj2.get_data();
    int N = obj1.get_size();

    float * d_v1, * d_v2, * d_o;
    cudaMallocManaged(&d_v1, N*sizeof(float));
    cudaMallocManaged(&d_v2, N*sizeof(float));

    cudaMemcpy(d_v1, h_v1, N*sizeof(float), cudaMemcpyHostToDevice);
    cudaMemcpy(d_v2, h_v2, N*sizeof(float), cudaMemcpyHostToDevice);

    int threads = THREADSPERBLOCK;
    int blocks = (N+threads-1)/threads;

    float *sum_ptr;
    cudaError_t er = cudaMallocManaged(&sum_ptr, blocks*sizeof(float));
    if (er != cudaSuccess)
    {
        printf("1 %s\n",cudaGetErrorString(er));
        exit(1);
    }

    kernel_dot<<<blocks,threads>>>(d_v1, d_v2, N, sum_ptr);
    cudaDeviceSynchronize();
    cudaError_t error;
    error = cudaGetLastError();
    if (error != cudaSuccess)
    {
        printf("0 %s\n",cudaGetErrorString(error));
        exit(1);
    }

    float sum = 0.0;
    for (int i = 0; i < blocks; ++i) {
        sum += sum_ptr[i];
    }

    cudaFree(d_v1);
    cudaFree(d_v2);
    cudaFree(sum_ptr);

    return sum;
}

float thrust_inner_product(EMData &obj1, EMData &obj2) {
    int N = obj1.get_size();
    float * d_ptr_1 = obj1.get_data();
    float * d_ptr_2 = obj2.get_data();
    DV d_v1(d_ptr_1, d_ptr_1+N);
    DV d_v2(d_ptr_2, d_ptr_2+N);
    
    return thrust::inner_product(d_v1.begin(),d_v1.end(),
                                 d_v2.begin(),
                                 0.0f);
}

float thrust_transform_reduce(EMData &obj1, EMData &obj2) {
    int  N = obj1.get_size();
    float * d_ptr_1 = obj1.get_data();
    float * d_ptr_2 = obj2.get_data();
    DV d_v1(d_ptr_1, d_ptr_1+N);
    DV d_v2(d_ptr_2, d_ptr_2+N);
    DV d_o(N);

    thrust::transform(d_v1.begin(),d_v1.end(),
                      d_v2.begin(),
                      d_o.begin(),
                      thrust::multiplies<float>());
    
    return thrust::reduce(d_o.begin(), d_o.end());
}

float cuda_cublas(EMData &obj1, EMData &obj2) {
    cublasHandle_t handle;
    float * h_v1 = obj1.get_data();
    float * h_v2 = obj2.get_data();
    int N = obj1.get_size();

    float * d_v1, * d_v2, * d_o;
    cudaMallocManaged(&d_v1, N*sizeof(float));
    cudaMallocManaged(&d_v2, N*sizeof(float));

    cudaMemcpy(d_v1, h_v1, N*sizeof(float), cudaMemcpyHostToDevice);
    cudaMemcpy(d_v2, h_v2, N*sizeof(float), cudaMemcpyHostToDevice);
    float *sum_ptr;
    cudaError_t er = cudaMallocManaged(&sum_ptr, sizeof(float));
    if (er != cudaSuccess)
    {
        printf("1 %s\n",cudaGetErrorString(er));
        exit(1);
    }

    *sum_ptr = 0.0f;


//    cublasSdot (handle, N,
//                d_v1, 1,
//                d_v2, 1,
//                sum_ptr);

    cublasDestroy(handle);

    float sum = *sum_ptr;
    cudaFree(sum_ptr);

    return sum;
}
