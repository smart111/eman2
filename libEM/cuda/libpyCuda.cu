#include <boost/python.hpp>
#include "dot.h"

using namespace boost::python;


BOOST_PYTHON_MODULE(libpyCuda)
        {
            def("cuda_hello", cuda_hello);
            def("cpp_dot", cpp_dot);
        };
