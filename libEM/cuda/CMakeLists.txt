add_library(pyCuda SHARED "")

target_sources(pyCuda PRIVATE
			   dot.cu
			   libpyCuda.cu
			   )

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

install(TARGETS pyCuda
		DESTINATION ${SP_DIR}
		COMPONENT Cuda
		)

add_custom_target(Cuda
				  COMMAND ${CMAKE_COMMAND} -DCOMPONENT=Cuda -P cmake_install.cmake
				  DEPENDS pyCuda
				  )
