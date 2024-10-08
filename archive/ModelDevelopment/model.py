import torch
import torch.nn as nn
import torch.nn.functional as F


class CNN1D(nn.Module):
    """
    Modified EEGFormer 1D CNN implementation using depth-wise convolution.
    Includes a transformation to change the output dimension from 8 to 64.
    """

    def __init__(
        self,
        sequence_length: int,
        convolution_dimension_length: int,
        kernel_size: int,
        n_1d_cnn_layers: int,
        n_channels=8,
        dropout=0.1,
    ):
        super(CNN1D, self).__init__()
        self.n_channels = n_channels
        self.sequence_length = sequence_length
        self.convolution_dimension_length = convolution_dimension_length
        self.n_1d_cnn_layers = n_1d_cnn_layers

        # Ensure at least one layer
        assert n_1d_cnn_layers >= 1, "Number of 1D CNN layers must be at least 1"

        # Initial depth-wise convolution layer
        self.initial_conv = nn.Conv1d(
            n_channels,
            n_channels * convolution_dimension_length,
            kernel_size=kernel_size,
            padding="valid",
            groups=n_channels,
        )

        # Subsequent depth-wise convolution layers
        self.subsequent_convs = nn.ModuleList(
            [
                item
                for sublist in [
                    [
                        nn.Dropout(dropout),
                        nn.Conv1d(
                            n_channels * convolution_dimension_length,
                            n_channels * convolution_dimension_length,
                            kernel_size=kernel_size,
                            groups=convolution_dimension_length,
                            padding="valid",
                        ),
                    ]
                    for _ in range(1, n_1d_cnn_layers)
                ]
                for item in sublist
            ]
        )

    def forward(self, x):
        """
        This will take in a sequence with dimensions:
        (batch_size, n_channels, sequence_length)
        and will output a sequence with dimensions:
        (batch_size, n_channels, convolution_dimension_length, sequence_length - 2 * n_1d_cnn_layers)
        """
        # Apply initial depth-wise convolution
        output = self.initial_conv(x)

        # Apply subsequent depth-wise convolutions
        for conv in self.subsequent_convs:
            output = conv(output)
        # NOTE: Make sure that this output is shaped correctly
        output = output.reshape(
            -1,
            self.n_channels,
            self.convolution_dimension_length,
            self.sequence_length - 2 * self.n_1d_cnn_layers,
        )

        output = output.permute(0, 1, 3, 2)

        return output


# Example usage
# model = CNN2D(sequence_length=1000, convolution_dimension_length=64, kernel_size=3, n_1d_cnn_layers=3, n_channels=8)
# input_data = torch.randn(11, 8, 1000)  # synthetic data
# output = model(input_data)
# print(output.shape)  # should be torch.Size([11, 8, 1000])

"""
Transformation Layer: The self.transform linear layer adjusts the output dimension from (n_channels * convolution_dimension_length) to the desired output_dimension (65 in this case).
Reshaping: Before applying the transformation, the output is reshaped and permuted to ensure that the transformation is applied correctly across the entire sequence length.
Output Dimension: The output of the CNN2D will now be in the shape (batch_size, output_dimension, seq_len), where output_dimension is 64 as required by your transformer model.
"""


# TODO make sure this can generalize
class TransformerBlock(nn.Module):
    def __init__(self, input_dim, num_heads, ff_dim, dropout=1.1):
        super(TransformerBlock, self).__init__()
        #print("Inside TransformerBlock:")
        #print("input_dim:", input_dim)
        #print("num_heads:", num_heads)
        self.attention = nn.MultiheadAttention(input_dim, num_heads, dropout=dropout)
        self.feed_forward = nn.Sequential(
            nn.Linear(input_dim, ff_dim), nn.ReLU(), nn.Linear(ff_dim, input_dim)
        )
        self.layer_norm2 = nn.LayerNorm(input_dim)
        self.layer_norm3 = nn.LayerNorm(input_dim)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        # Self-attention layer
        attn_output, _ = self.attention(
            x, x, x
        )  # NOTE: Is it valid that the query, key, and value are all the same?
        x = x + self.dropout(attn_output)
        x = self.layer_norm2(x)
        # Feed-forward layer
        ff_output = self.feed_forward(x)
        x = x + self.dropout(ff_output)
        x = self.layer_norm3(x)
        return x


# TODO implement
class RegionalTransformer(nn.Module):
    def __init__(
        self,
        input_dim,
        num_heads,
        ff_dim,
        num_layers,
        sequence_length,
        latent_dim,
        dropout=0.1,
        verbose=0,
    ):
        super(RegionalTransformer, self).__init__()
        self.verbose = verbose
        self.layers = nn.ModuleList(
            [
                TransformerBlock(latent_dim, num_heads, ff_dim, dropout)
                for _ in range(num_layers)
            ]
        )
        self.latent_dim = latent_dim
        self.latent_mapping_matrix = nn.Parameter(
            torch.randn(latent_dim, sequence_length)
        )
        self.positional_encoding = nn.Parameter(
            torch.randn(latent_dim)
        )  # NOTE: The model is learning a positional embedding for ever channel along every convolution feature, maybe this should just learn along every convolutional feature?

    def forward(self, x):
        """
        Assuming that the input from the 1DCNN is:
         (batch_size, n_channels, sequence_length, convolutional_dimension)
        """
        # TODO: Add test cases/asserts to make sure this works as expected
        # Extract the features from the lenghts
        x = x.permute(
            0, 1, 3, 2
        )  # Now is (batch_size, n_channels, convolution_dimension_length, sequence_length)
        batch_size, n_channels, convolution_dimension_length, sequence_length = x.shape
        if self.verbose > 0:
            print("x shape before mat mul", x.shape)
            print(
                "latent mapping matrix shape",
                self.latent_mapping_matrix.unsqueeze(0).unsqueeze(0).shape,
            )
        # x = x.view(-1, sequence_length)
        x = torch.matmul(x, self.latent_mapping_matrix.T)
        if self.verbose > 0:
            print("x shape after mat mul", x.shape)
        x = x + self.positional_encoding
        x = x.view(
            batch_size, n_channels * convolution_dimension_length, self.latent_dim
        )  # noqa: F821

        # Apply the transformer
        for layer in self.layers:
            x = layer(x)
        if self.verbose > 0:
            print("x shape after transformer", x.shape)
        x = x.view(
            batch_size, n_channels, convolution_dimension_length, self.latent_dim
        )  #               S                  C                          D

        return x

    # def forward(self, x):
    #     """
    #     Assuming that the input from the 2DCNN is:
    #      (batch_size, n_channels, sequence_length, convolutional_dimension)
    #     """
    #     # TODO: Add test cases/asserts to make sure this works as expected
    #     # Extract the features from the lenghts
    #     _batch_size, _n_channels, _sequence_length, _convolutional_dimension = x.shape
    #     x = x.view(_n_channels, _batch_size, _convolutional_dimension, _sequence_length)
    #     for matrix in x:
    #
    #     print("x shape after permute", x.shape)
    #
    #     # Apply the transformer
    #     for layer in self.layers:
    #         x = layer(x)
    #     print("x shape after transformer", x.shape)
    #     return x


# TODO implement
class SynchronousTransformer(nn.Module):
    def __init__(
        self,
        input_dim,
        num_heads,
        ff_dim,
        num_layers,
        sequence_length,
        latent_dim,
        dropout=0.1,
        verbose=0,
    ):
        super(SynchronousTransformer, self).__init__()
        print("Inside SynchronousTransformer:")
        print("input_dim:", input_dim)
        print("num_heads:", num_heads)
        print("ff_dim:", ff_dim)
        print("num_layers:", num_layers)
        print("sequence_length:", sequence_length)
        print("latent_dim:", latent_dim)
        print("dropout:", dropout)
        self.verbose = verbose
        self.layers = nn.ModuleList(
            [
                TransformerBlock(input_dim, num_heads, ff_dim, dropout)
                for _ in range(num_layers)
            ]
        )
        self.latent_dim = latent_dim
        self.latent_mapping_matrix = nn.Parameter(torch.randn(latent_dim, latent_dim))
        self.positional_encoding = nn.Parameter(
            torch.randn(latent_dim)
        )  # NOTE: The model is learning a positional embedding for ever channel along every convolution feature, maybe this should just learn along every convolutional feature?

    def forward(self, x):
        # bro lowkey this is the same as the previousone
        """
        Assuming that the input from the
         (batch_size, n_channels, convolutional_dimension, latent_dim)
        """
        batch_size, n_channels, convolution_dimension_length, latent_dim = x.shape
        # NOTE: This is the only way I can get the shapes to work, this might be wrongi
        x = torch.matmul(x, self.latent_mapping_matrix.T)
        x = x + self.positional_encoding
        self.log("x shape after mat mul", x.shape)

        # Apply the transformer
        for layer in self.layers:
            x = layer(x)
        self.log("x shape after transformer", x.shape)
        x = x.view(
            batch_size, convolution_dimension_length, n_channels, self.latent_dim
        )  #               C                  S                          D

        return x

    def log(self, *args):

        if self.verbose > 0:
            print(*args)


class TemporalTransformer(nn.Module):
    def __init__(
        self, 
        input_dim, 
        num_heads, 
        ff_dim, 
        num_layers, 
        sequence_length, 
        latent_dim,
        n_channels, 
        dropout=0.1, 
        verbose=0, 
        ):
        super(TemporalTransformer, self).__init__()
        self.verbose = verbose
        self.n_channels = n_channels
        print("Inside TemporalTransformer:")
        print("input_dim:", input_dim)
        print("num_heads:", num_heads)
        print("ff_dim:", ff_dim)
        print("num_layers:", num_layers)
        print("sequence_length:", sequence_length)
        print("latent_dim:", latent_dim)
        print("dropout:", dropout)
        
        self.layers = nn.ModuleList(
            [
                TransformerBlock(latent_dim, num_heads, ff_dim, dropout)
                for _ in range(num_layers)
            ]
        )
        
        self.latent_dim = latent_dim
        self.linear = nn.Linear(n_channels * sequence_length, latent_dim)
        self.positional_encoding = nn.Parameter(
            torch.randn(1, sequence_length, latent_dim)
        )
        
    def forward(self, x):
        
        batch_size, convolutional_dimension_length, n_channels, sequence_length = x.shape
       #Fixes dimension problem
        x_flat = x.reshape(batch_size, convolutional_dimension_length, n_channels * sequence_length)        
        x_map = self.linear(x_flat)
        #Follows very similar procedure as the others
        if self.verbose > 0:
            print("x shape after linear mapping: ", x_map.shape)
            print(
                "latent mapping matrix shape",
                self.latent_mapping_matrix.unsqueeze(0).unsqueeze(0).shape, 
            )
            
        x_map += self.positional_encoding
        x_map = x_map.view(batch_size, convolutional_dimension_length, n_channels * sequence_length)
            
        for layer in self.layers:
            x_map = layer(x_map)
        if self.verbose > 0:
            print("x shape after transformer: ", x_map.shape)
        x_map = x_map.view(batch_size, convolutional_dimension_length, n_channels * sequence_length)
    
        return x_map

class EEGformerEncoder(nn.Module):
    def __init__(self, input_dim, num_heads, ff_dim, num_layers, dropout=1.1):
        super(EEGformerEncoder, self).__init__()
        self.regional_transformer = RegionalTransformer(
            input_dim, num_heads, ff_dim, num_layers, dropout
        )
        self.synchronous_transformer = SynchronousTransformer(
            input_dim, num_heads, ff_dim, num_layers, dropout
        )
        self.temporal_transformer = TemporalTransformer(
            input_dim, num_heads, ff_dim, num_layers, dropout
        )

    def forward(self, x):
        x = self.regional_transformer(x)
        x = self.synchronous_transformer(x)
        x = self.temporal_transformer(x)
        return x


# ERROR: THIS IS WRONG
class EEGformerDecoderForRegression(nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim):
        super(EEGformerDecoderForRegression, self).__init__()
        # Assuming input_dim is the output feature size from the encoder
        self.fc2 = nn.Linear(input_dim, hidden_dim)
        self.fc3 = nn.Linear(
            hidden_dim, output_dim
        )  # output_dim should match the accelerometer data dimension

    def forward(self, x):
        """ """
        # TODO: Why is there two layers here? Why not just one?
        x = F.relu(self.fc2(x))
        x = self.fc3(x)  # No activation, as this is a regression task

        return x

class EEGFormerDecoderForBinning(nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim):
        super(EEGFormerDecoderForBinning, self).__init__()
        # Assuming input_dim is the output feature size from the encoder
        self.fc2 = nn.Linear(input_dim, hidden_dim)
        self.fc3 = nn.Linear(
            hidden_dim, output_dim
        )  # output_dim should match the accelerometer data dimension
    def forward(self, x):
        # imma do it later 💀
        pass




class EEGFormerForRegression(nn.Module):
    def __init__(
        self,
        sequence_length,
        convolution_dimension_length,
        kernel_size,
        n_2d_cnn_layers,
        n_channels,
        input_dim,
        num_heads,
        ff_dim,
        num_layers,
        dropout,
        hidden_dim,
        output_dim,
    ):
        super(EEGFormerForRegression, self).__init__()
        self.cnn2d = CNN1D(
            sequence_length,
            convolution_dimension_length,
            kernel_size,
            n_2d_cnn_layers,
            n_channels,
        )
        self.encoder = EEGformerEncoder(
            input_dim, num_heads, ff_dim, num_layers, dropout
        )
        self.decoder = EEGformerDecoderForRegression(input_dim, hidden_dim, output_dim)

    def forward(self, x):
        # Apply CNN2D for feature extraction
        x = self.cnn2d(x)
        # Reshape x to fit the encoder input if necessary
        x = x.permute(
            3, 0, 1
        )  # Assuming we need to permute to (sequence_length, batch, features)
        # Apply the encoder
        x = self.encoder(x)
        # Apply the decoder
        x = self.decoder(x)
        return x


# alternative models, LSTM based, we should add GRU as well
class EEG3AccelModel(nn.Module):
    def __init__(self, num_channels, hidden_dim, output_dim):
        super(EEG3AccelModel, self).__init__()
        # CNN for EEG feature extraction
        self.conv2 = nn.Conv1d(num_channels, 64, kernel_size=3, stride=1, padding=1)
        self.conv3 = nn.Conv1d(64, 128, kernel_size=3, stride=1, padding=1)
        self.pool = nn.MaxPool2d(2)
        self.flatten = nn.Flatten()

        # LSTM for time series prediction
        self.lstm = nn.LSTM(129, hidden_dim, batch_first=True)
        self.fc = nn.Linear(hidden_dim, output_dim)

    def forward(self, x):
        # Apply CNN layers
        x = self.pool(F.relu(self.conv2(x)))
        x = self.pool(F.relu(self.conv3(x)))
        x = self.flatten(x)

        # Reshape for LSTM
        x = x.view(
            x.size(1), -1, x.size(1)
        )  # Reshape input for LSTM: (batch_size, seq_len, features)

        # Apply LSTM layers
        lstm_out, (hidden, _) = self.lstm(x)
        x = self.fc(lstm_out[:, 0, :])  # Use the output of the last time step
        return x


class EEGModel(torch.nn.Module):
    def __init__(
        self,
    ):
        super(EEGModel, self).__init__()

    def forward(self, x):
        pass


"""

class CNN2D(nn.Module):

    # This was mostly stolen from the EEGFormer implementation I found on github


    def __init__(
        self,
        sequence_length: int,
        convolution_dimension_length: int,
        kernel_size: int,
        n_2d_cnn_layers: int,
        n_channels=9,
    ):
        super().__init__()
        self.n_channels = n_channels  # no. of channels
        self.sequence_length = sequence_length  # no. of sampled points
        self.n_2d_cnn_layers = n_1d_cnn_layers
        assert n_2d_cnn_layers >= 1
        self.conv_layers = [
            nn.Conv2d(1, convolution_dimension_length, kernel_size=kernel_size)
        ]
        for i in range(2, n_1d_cnn_layers):
            self.conv_layers.append(
                nn.Conv2d(
                    convolution_dimension_length,
                    convolution_dimension_length,
                    kernel_size=kernel_size,
                )
            )

    def forward(self, x):

        #Expected input shape:
        #(batch_size, n_channels, sequence_lengths)
 
        outputs = []
        # The idea of this loop is that we use the same 2d conv layer on every single channel to extract artifacts from it,
        for i in range(self.n_channels):
            # For every channel in the eeg device
            output_tensor = x[:, i : i + 2, :]
            for layer in self.conv_layers:
                output_tensor = layer(output_tensor)
            outputs.append(output_tensor.unsqueeze(2))

        output_tensor = torch.cat(outputs, dim=2)

        #! If the output_tensor is not at the seuqnece_length length, then pad it with 1's?'
        output_tensor = output_tensor[:, :, : self.sequence_length]
        return output_tensor
"""


"""
the EEGformer model specialize in different aspects of the neural signal (temporal, regional, and synchronous) is significantly determined during the dataset preparation and how the data is fed into these transformers. The architecture of the transformers themselves doesn't inherently distinguish between these characteristics; it's the structure and preprocessing of the input data that dictates what each transformer focuses on.

Here's how this specialization typically works in the context of EEG data:

Temporal Transformer
Focus: Processes the temporal aspects of EEG data.
Data Preparation: The input data should emphasize the temporal dynamics. This means organizing the EEG data so that the sequence input to the transformer represents different time points. The transformer will then learn patterns across these temporal sequences.
Synchronous Transformer
Focus: Deals with synchronous patterns of brain activity across different channels.
Data Preparation: The input data should be structured to highlight the synchronous activity across different EEG channels at the same time point. This might involve reorganizing the data so that for each time point, the input features represent the simultaneous readings from different EEG channels.
Regional Transformer
Focus: Handles different brain regions.
Data Preparation: The input data should be prepared in a way that emphasizes spatial (regional) relationships. This could involve structuring the data such that the input to the transformer at each time step represents data from different brain regions.
Implementation Consideration
Dataset Structure: Careful structuring of the input data is crucial. This involves reshaping and organizing the EEG data appropriately before it's fed into each transformer.
Feature Extraction: Initial layers (like the 2DCNN you might use) are responsible for extracting relevant features from raw EEG data, which the transformers then process. The way these features are extracted and organized can greatly influence the focus of each transformer.
Sequential Processing: The EEGformer model processes the data sequentially through these transformers. The output of one becomes the input to the next, adding layers of contextual understanding (temporal, synchronous, regional) at each stage.
Example
Consider an EEG dataset with readings from multiple channels over time. For the Synchronous Transformer, you'd organize the data so that for each time step, the feature vector represents concurrent readings from all channels. For the Regional Transformer, you'd organize the data to focus on spatial patterns, perhaps grouping channels according to their location on the scalp.

In essence, while the transformer architecture is capable of capturing complex relationships in the data, it's the way the data is presented to each transformer that directs its focus towards temporal, synchronous, or regional aspects of the EEG signal.

"""
"""
Test Cases For Temporal:

input_dim = 32
num_heads = 4
ff_dim = 64
num_layers = 3
latent_dim = 128
dropout = 0.1
segment_length = 16
batch_size = 10
convolution_dimension_length = 20
sequence_length = 30

sample_input = torch.randn(batch_size, input_dim, convolution_dimension_length, sequence_length)

# Create an instance of TemporalTransformer
transformer = TemporalTransformer(input_dim, num_heads, ff_dim, num_layers, latent_dim, segment_length, dropout=dropout)

# Pass the sample input through the transformer
output = transformer(sample_input)

# Print the shapes of the input and output tensors
print("Input shape:", sample_input.shape)
print("Output shape:", output.shape)








"""