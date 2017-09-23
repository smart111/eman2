set(CMAKE_CUDA_FLAGS "-arch=compute_30 -code=sm_30,compute_30 --std=c++11")
add_library(dot STATIC dot.cu)
set_target_properties(dot PROPERTIES CUDA_SEPARABLE_COMPILATION ON)
target_link_libraries(dot EM2)

add_library(pyCuda SHARED libpyCuda.cu)
target_link_libraries(pyCuda dot -lcublas)

add_executable(e2dot main.cu)
set_target_properties(e2dot PROPERTIES CUDA_SEPARABLE_COMPILATION ON)

target_link_libraries(e2dot dot)

if(WIN32)
	set(suffix .pyd)
else()
	set(suffix .so)
endif()

set_target_properties(pyCuda
					  PROPERTIES CUDA_SEPARABLE_COMPILATION ON
					  PREFIX lib
					  SUFFIX ${suffix}
					  )

find_package(Boost COMPONENTS python REQUIRED)
set_target_properties(Boost::python
					  PROPERTIES
					  INTERFACE_COMPILE_DEFINITIONS BOOST_PYTHON_NO_PY_SIGNATURES
					  INTERFACE_LINK_LIBRARIES Python::Python
					  )

target_link_libraries(pyCuda Boost::python)

install(TARGETS pyCuda dot
		DESTINATION ${SP_DIR}
		COMPONENT Cuda
		)

install(TARGETS e2dot
		DESTINATION bin
		COMPONENT Cuda
		)

add_custom_target(Cuda
				  COMMAND ${CMAKE_COMMAND} -DCOMPONENT=Cuda -P cmake_install.cmake
				  DEPENDS pyCuda dot e2dot
				  )
