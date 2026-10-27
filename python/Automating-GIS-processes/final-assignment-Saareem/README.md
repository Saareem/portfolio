# Final Assignment

### Status

Once you are finished with the final assignment, edit this readme and add "x" to the correct box:

* [x] Submitted

* [ ] I'm still working on my final assignment. 


### Instructions

The only Python package not available in the JupyterLab instance was the `OWSLib`. The installation is already included in the notebook but if it does not contain it for some reason, it should be possible to install it with
```
pip install OWSLib
```

**NOTE:** Running the notebook takes roughly 10 minutes.
## Topic: 
Urban indicators for cities of Helsinki and Tampere, Finland

### Structure of this repository:
The code is organized to `final_assignment.ipynb` which is the actual notebook that contains all the text and some visualization and minor calculation code. Most of the actual code is organized as functions in modules `street_network_metrics.py`, `street_network_metrics.py` and `utils.py`. 
### Input data:
All the input data is downloaded on demand either from Overpass.api (using `osmnx`) or from WFS interfaces of **Paituli** and **Statistics Finland**.  

