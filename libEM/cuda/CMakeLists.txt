add_library(pyCuda SHARED "")

target_sources(pyCuda PRIVATE
			   dot.cu
			   libpyCuda.cu
			   )

set_target_properties(pyCuda
					  PROPERTIES CUDA_SEPARABLE_COMPILATION ON
					  )

install(TARGETS pyCuda
		DESTINATION ${SP_DIR}
		COMPONENT Cuda
		)

add_custom_target(Cuda
				  COMMAND ${CMAKE_COMMAND} -DCOMPONENT=Cuda -P cmake_install.cmake
				  DEPENDS pyCuda
				  )
