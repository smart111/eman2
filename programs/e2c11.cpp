#include <iostream>
#include "emdata.h"

using namespace std;
using namespace EMAN;

int main() {
    
    int i = 6;
    int f = 11;
    
    auto a = i;
    
    cout<<"Hello there!\n"
            <<a
        <<endl;

    EMData im;
    im.set_size(128,128);
    im.process_inplace("testimage.scurve");
    im.write_image("mytest.hdf");
    
    return 0;
}
