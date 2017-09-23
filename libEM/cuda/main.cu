#include <iostream>
#include "dot.h"

using namespace std;

int main(int argc, char *argv[]){
    cout<<"Running "
        <<argv[0]
        <<" ..."
        <<endl;
    
    cuda_hello();
    
    cout<<"Finished..."<<endl;
    
    return 0;
}
