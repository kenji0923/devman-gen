# Overview
This package is a code generator to bridge users and a device interface with resource management control.
Let's think about we have a multichannel device (e.g. CAEN high voltage supply), which multiple users are using through client softwares.
Libraries to control the device (e.g. https://pypi.org/project/caen-libs/) is supplied and we know what functions are exposed.
We want to avoid a user changes device channel settings which another user is controlling.
So this package generates a bridge library with the same signatures as the original library, but inside each function, it sends a request to another server (manager).
The server will check if the request sender has the right to control the required resource, and then if it passed execute the real instruction, return data from the device to the sender.

# Implementation detail
- If possible, the client and server library should be generated automatically with the same signatures with the original control library. Or if it is too complicated, it requires a user to list up signatures.
- Each client should have unique name, which is configurable by a user with duplicate check, and can request acquire / release the management of resources. The server will store the ownership in a simple databse.
- Communications between the client and server should have low latency and possibly highly portable by using such as gRPC.
- The generator can use python. For now, it is okay if it can handle original libraries prepared for python. Let's start from caen-libs.
