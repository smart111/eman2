add_custom_target(RTPYEMFiles
				  COMMAND ${CMAKE_COMMAND} -DCOMPONENT=RTPYEMFiles -P cmake_install.cmake
				  )

FILE(GLOB testprograms "${CMAKE_CURRENT_SOURCE_DIR}/*.py")
INSTALL(PROGRAMS ${testprograms}
		DESTINATION    test/rt/pyem
		COMPONENT RTPYEMFiles
)
