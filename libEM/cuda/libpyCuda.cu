#include <boost/python.hpp>
#include "dot.h"

using namespace boost::python;


BOOST_PYTHON_MODULE(libpyCuda)
        {
            def("cuda_hello", cuda_hello);
            def("cpp_dot", cpp_dot);
            def("cuda_dot", cuda_dot);
            def("thrust_inner_product", thrust_inner_product);
            def("thrust_transform_reduce", thrust_transform_reduce);
        };
