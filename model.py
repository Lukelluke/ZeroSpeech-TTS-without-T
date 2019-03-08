# -*- coding: utf-8 -*- #
"""*********************************************************************************************"""
#   FileName     [ model.py ]
#   Synopsis     [ model architecture ]
#   Author       [ Ting-Wei Liu (Andi611) ]
#   Copyright    [ Copyleft(c), NTUEE, NTU, Taiwan ]
"""*********************************************************************************************"""


###############
# IMPORTATION #
###############
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable


def pad_layer(inp, layer, seg_len, is_2d=False):
	if type(layer.kernel_size) == tuple:
		kernel_size = layer.kernel_size[0]
	else:
		kernel_size = layer.kernel_size
	if not is_2d:
		if kernel_size % 2 == 0:
			pad = (kernel_size//2, kernel_size//2 - 1)
		else:
			pad = (kernel_size//2, kernel_size//2)
	else:
		if kernel_size % 2 == 0:
			pad = (kernel_size//2, kernel_size//2 - 1, kernel_size//2, kernel_size//2 - 1)
		else:
			pad = (kernel_size//2, kernel_size//2, kernel_size//2, kernel_size//2)
	# padding
	inp = F.pad(inp, 
			pad=pad,
			mode='constant' if seg_len < 64 else 'reflect')
	out = layer(inp)
	return out


def pixel_shuffle_1d(inp, upscale_factor=2):
	batch_size, channels, in_width = inp.size()
	channels //= upscale_factor
	
	out_width = in_width * upscale_factor
	inp_view = inp.contiguous().view(batch_size, channels, upscale_factor, in_width)
	shuffle_out = inp_view.permute(0, 1, 3, 2).contiguous()
	shuffle_out = shuffle_out.view(batch_size, channels, out_width)
	return shuffle_out


def upsample(x, scale_factor=2):
	x_up = F.interpolate(x, scale_factor=2, mode='nearest')
	return x_up


def RNN(inp, layer):
	inp_permuted = inp.permute(2, 0, 1)
	state_mul = (int(layer.bidirectional) + 1) * layer.num_layers
	zero_state = Variable(torch.zeros(state_mul, inp.size(0), layer.hidden_size))
	zero_state = zero_state.cuda() if torch.cuda.is_available() else zero_state
	out_permuted, _ = layer(inp_permuted, zero_state)
	out_rnn = out_permuted.permute(1, 2, 0)
	return out_rnn


def linear(inp, layer):
	batch_size = inp.size(0)
	hidden_dim = inp.size(1)
	seg_len = inp.size(2)
	inp_permuted = inp.permute(0, 2, 1)
	inp_expand = inp_permuted.contiguous().view(batch_size*seg_len, hidden_dim)
	out_expand = layer(inp_expand)
	out_permuted = out_expand.view(batch_size, seg_len, out_expand.size(1))
	out = out_permuted.permute(0, 2, 1)
	return out


def append_emb(emb, expand_size, output):
	emb = emb.unsqueeze(dim=2)
	emb_expand = emb.expand(emb.size(0), emb.size(1), expand_size)
	output = torch.cat([output, emb_expand], dim=1)
	return output


"""
	Reference: https://gist.github.com/yzh119/fd2146d2aeb329d067568a493b20172f
	input: [*, n_class]
	return: [*, n_class] an one-hot vector
"""
def gumbel_softmax(logits, temperature=0.1):
	
	def _sample_gumbel(shape, eps=1e-20):
		U = torch.rand(shape)
		dist = -Variable(torch.log(-torch.log(U + eps) + eps))
		return dist.cuda() if torch.cuda.is_available() else dist

	def _gumbel_softmax_sample(logits, temperature):
		y = logits + _sample_gumbel(logits.size())
		return F.softmax(y / temperature, dim=-1)

	y = _gumbel_softmax_sample(logits, temperature)
	shape = y.size()
	_, ind = y.max(dim=-1)
	y_hard = torch.zeros_like(y).view(-1, shape[-1])
	y_hard.scatter_(1, ind.view(-1, 1), 1)
	y_hard = y_hard.view(*shape)
	return (y_hard - y).detach() + y


class PatchDiscriminator(nn.Module):
	def __init__(self, n_class=33, ns=0.2, dp=0.1, seg_len=128):
		super(PatchDiscriminator, self).__init__()
		self.ns = ns
		self.seg_len = seg_len
		self.conv1 = nn.Conv2d(1, 64, kernel_size=5, stride=2)
		self.conv2 = nn.Conv2d(64, 128, kernel_size=5, stride=2)
		self.conv3 = nn.Conv2d(128, 256, kernel_size=5, stride=2)
		self.conv4 = nn.Conv2d(256, 512, kernel_size=5, stride=2)
		self.conv5 = nn.Conv2d(512, 512, kernel_size=5, stride=2)
		self.conv6 = nn.Conv2d(512, 32, kernel_size=1)
		if self.seg_len == 128:
			self.conv7 = nn.Conv2d(32, 1, kernel_size=(17, 4))
			self.conv_classify = nn.Conv2d(32, n_class, kernel_size=(17, 4))
		elif self.seg_len == 64:
			self.conv7 = nn.Conv2d(32, 1, kernel_size=(17, 2))
			self.conv_classify = nn.Conv2d(32, n_class, kernel_size=(17, 2))
		elif self.seg_len == 32:
			self.conv7 = nn.Conv2d(32, 1, kernel_size=(17, 1))
			self.conv_classify = nn.Conv2d(32, n_class, kernel_size=(17, 1))
		else:
			raise NotImplementedError('Segement length {} is not supported!'.format(seg_len))
		self.drop1 = nn.Dropout2d(p=dp)
		self.drop2 = nn.Dropout2d(p=dp)
		self.drop3 = nn.Dropout2d(p=dp)
		self.drop4 = nn.Dropout2d(p=dp)
		self.drop5 = nn.Dropout2d(p=dp)
		self.drop6 = nn.Dropout2d(p=dp)
		self.ins_norm1 = nn.InstanceNorm2d(self.conv1.out_channels)
		self.ins_norm2 = nn.InstanceNorm2d(self.conv2.out_channels)
		self.ins_norm3 = nn.InstanceNorm2d(self.conv3.out_channels)
		self.ins_norm4 = nn.InstanceNorm2d(self.conv4.out_channels)
		self.ins_norm5 = nn.InstanceNorm2d(self.conv5.out_channels)
		self.ins_norm6 = nn.InstanceNorm2d(self.conv6.out_channels)

	def conv_block(self, x, conv_layer, after_layers):
		out = pad_layer(x, conv_layer, self.seg_len, is_2d=True)
		out = F.leaky_relu(out, negative_slope=self.ns)
		for layer in after_layers:
			out = layer(out)
		return out 

	def forward(self, x, classify=False):
		x = torch.unsqueeze(x, dim=1)
		out = self.conv_block(x, self.conv1, [self.ins_norm1, self.drop1])
		out = self.conv_block(out, self.conv2, [self.ins_norm2, self.drop2])
		out = self.conv_block(out, self.conv3, [self.ins_norm3, self.drop3])
		out = self.conv_block(out, self.conv4, [self.ins_norm4, self.drop4])
		out = self.conv_block(out, self.conv5, [self.ins_norm5, self.drop5])
		out = self.conv_block(out, self.conv6, [self.ins_norm6, self.drop6])
		# GAN output value
		val = self.conv7(out)
		val = val.view(val.size(0), -1)
		mean_val = torch.mean(val, dim=1)
		if classify:
			# classify
			logits = self.conv_classify(out)
			logits = logits.view(logits.size(0), -1)
			return mean_val, logits
		else:
			return mean_val


class SpeakerClassifier(nn.Module):
	def __init__(self, c_in=512, c_h=512, n_class=8, dp=0.1, ns=0.01, seg_len=128):
		super(SpeakerClassifier, self).__init__()
		self.dp = dp
		self.ns = ns
		self.seg_len = seg_len
		self.conv1 = nn.Conv1d(c_in, c_h, kernel_size=5)
		self.conv2 = nn.Conv1d(c_h, c_h, kernel_size=5)
		self.conv3 = nn.Conv1d(c_h, c_h, kernel_size=5)
		self.conv4 = nn.Conv1d(c_h, c_h, kernel_size=5)
		self.conv5 = nn.Conv1d(c_h, c_h, kernel_size=5)
		self.conv6 = nn.Conv1d(c_h, c_h, kernel_size=5)
		self.conv7 = nn.Conv1d(c_h, c_h//2, kernel_size=3)
		self.conv8 = nn.Conv1d(c_h//2, c_h//4, kernel_size=3)
		if self.seg_len == 128:
			self.conv9 = nn.Conv1d(c_h//4, n_class, kernel_size=16)
		elif self.seg_len == 64:
			self.conv9 = nn.Conv1d(c_h//4, n_class, kernel_size=8)
		elif self.seg_len == 32:
			self.conv9 = nn.Conv1d(c_h//4, n_class, kernel_size=4)
		else:
			raise NotImplementedError('Segement length {} is not supported!'.format(seg_len))
		self.drop1 = nn.Dropout(p=dp)
		self.drop2 = nn.Dropout(p=dp)
		self.drop3 = nn.Dropout(p=dp)
		self.drop4 = nn.Dropout(p=dp)
		self.ins_norm1 = nn.InstanceNorm1d(c_h)
		self.ins_norm2 = nn.InstanceNorm1d(c_h)
		self.ins_norm3 = nn.InstanceNorm1d(c_h)
		self.ins_norm4 = nn.InstanceNorm1d(c_h//4)

	def conv_block(self, x, conv_layers, after_layers, res=True):
		out = x
		for layer in conv_layers:
			out = pad_layer(out, layer, self.seg_len)
			out = F.leaky_relu(out, negative_slope=self.ns)
		for layer in after_layers:
			out = layer(out)
		if res:
			out = out + x
		return out

	def forward(self, x):
		out = self.conv_block(x, [self.conv1, self.conv2], [self.ins_norm1, self.drop1], res=False)
		out = self.conv_block(out, [self.conv3, self.conv4], [self.ins_norm2, self.drop2], res=True)
		out = self.conv_block(out, [self.conv5, self.conv6], [self.ins_norm3, self.drop3], res=True)
		out = self.conv_block(out, [self.conv7, self.conv8], [self.ins_norm4, self.drop4], res=False)
		out = self.conv9(out)
		out = out.view(out.size()[0], -1)
		return out


class Decoder(nn.Module):
	def __init__(self, c_in=512, c_out=513, c_h=512, c_a=8, ns=0.2, seg_len=64):
		super(Decoder, self).__init__()
		self.ns = ns
		self.seg_len = seg_len
		self.conv1 = nn.Conv1d(c_h, 2*c_h, kernel_size=3)
		self.conv2 = nn.Conv1d(c_h, c_h, kernel_size=3)
		self.conv3 = nn.Conv1d(c_h, 2*c_h, kernel_size=3)
		self.conv4 = nn.Conv1d(c_h, c_h, kernel_size=3)
		self.conv5 = nn.Conv1d(c_h, 2*c_h, kernel_size=3)
		self.conv6 = nn.Conv1d(c_h, c_h, kernel_size=3)
		self.dense1 = nn.Linear(c_h, c_h)
		self.dense2 = nn.Linear(c_h, c_h)
		self.dense3 = nn.Linear(c_h, c_h)
		self.dense4 = nn.Linear(c_h, c_h)
		self.RNN = nn.GRU(input_size=c_h, hidden_size=c_h//2, num_layers=1, bidirectional=True)
		self.dense5 = nn.Linear(2*c_h + c_h, c_h)
		self.linear = nn.Linear(c_h, c_out)
		# normalization layer
		self.ins_norm1 = nn.InstanceNorm1d(c_h)
		self.ins_norm2 = nn.InstanceNorm1d(c_h)
		self.ins_norm3 = nn.InstanceNorm1d(c_h)
		self.ins_norm4 = nn.InstanceNorm1d(c_h)
		self.ins_norm5 = nn.InstanceNorm1d(c_h)
		# embedding layer
		self.input_emb = nn.Linear(c_in, c_h)
		self.emb1 = nn.Embedding(c_a, c_h)
		self.emb2 = nn.Embedding(c_a, c_h)
		self.emb3 = nn.Embedding(c_a, c_h)
		self.emb4 = nn.Embedding(c_a, c_h)
		self.emb5 = nn.Embedding(c_a, c_h)

	def conv_block(self, x, conv_layers, norm_layer, emb, res=True):
		# first layer
		x_add = x + emb.view(emb.size(0), emb.size(1), 1)
		out = pad_layer(x_add, conv_layers[0], self.seg_len)
		out = F.leaky_relu(out, negative_slope=self.ns)
		# upsample by pixelshuffle
		out = pixel_shuffle_1d(out, upscale_factor=2)
		out = out + emb.view(emb.size(0), emb.size(1), 1)
		out = pad_layer(out, conv_layers[1], self.seg_len)
		out = F.leaky_relu(out, negative_slope=self.ns)
		out = norm_layer(out)
		if res:
			x_up = upsample(x, scale_factor=2)
			out = out + x_up
		return out

	def dense_block(self, x, emb, layers, norm_layer, res=True):
		out = x
		for layer in layers:
			out = out + emb.view(emb.size(0), emb.size(1), 1)
			out = linear(out, layer)
			out = F.leaky_relu(out, negative_slope=self.ns)
		out = norm_layer(out)
		if res:
			out = out + x
		return out

	def forward(self, x, c):
		# conv layer
		out = self.conv_block(linear(x, self.input_emb), [self.conv1, self.conv2], self.ins_norm1, self.emb1(c), res=True)
		out = self.conv_block(out, [self.conv3, self.conv4], self.ins_norm2, self.emb2(c), res=True)
		out = self.conv_block(out, [self.conv5, self.conv6], self.ins_norm3, self.emb3(c), res=True)
		# dense layer
		out = self.dense_block(out, self.emb4(c), [self.dense1, self.dense2], self.ins_norm4, res=True)
		out = self.dense_block(out, self.emb4(c), [self.dense3, self.dense4], self.ins_norm5, res=True)
		emb = self.emb5(c)
		out_add = out + emb.view(emb.size(0), emb.size(1), 1)
		# rnn layer
		out_rnn = RNN(out_add, self.RNN)
		out = torch.cat([out, out_rnn], dim=1)
		out = append_emb(self.emb5(c), out.size(2), out)
		out = linear(out, self.dense5)
		out = F.leaky_relu(out, negative_slope=self.ns)
		out = linear(out, self.linear)
		out = torch.sigmoid(out)
		return out


class Encoder(nn.Module):
	def __init__(self, c_in=513, c_h1=128, c_h2=512, c_h3=128, ns=0.2, dp=0.5, enc_size=512, seg_len=64, enc_mode='continues'):
		super(Encoder, self).__init__()
		self.ns = ns
		self.enc_size = enc_size
		self.seg_len = seg_len
		self.enc_mode = enc_mode
		self.conv1s = nn.ModuleList(
				[nn.Conv1d(c_in, c_h1, kernel_size=k) for k in range(1, 8)]
			)
		self.conv2 = nn.Conv1d(len(self.conv1s)*c_h1 + c_in, c_h2, kernel_size=1)
		self.conv3 = nn.Conv1d(c_h2, c_h2, kernel_size=5)
		self.conv4 = nn.Conv1d(c_h2, c_h2, kernel_size=5, stride=2)
		self.conv5 = nn.Conv1d(c_h2, c_h2, kernel_size=5)
		self.conv6 = nn.Conv1d(c_h2, c_h2, kernel_size=5, stride=2)
		self.conv7 = nn.Conv1d(c_h2, c_h2, kernel_size=5)
		self.conv8 = nn.Conv1d(c_h2, c_h2, kernel_size=5, stride=2)
		self.dense1 = nn.Linear(c_h2, c_h2)
		self.dense2 = nn.Linear(c_h2, c_h2)
		self.dense3 = nn.Linear(c_h2, c_h2)
		self.dense4 = nn.Linear(c_h2, c_h2)
		self.RNN = nn.GRU(input_size=c_h2, hidden_size=c_h3, num_layers=1, bidirectional=True)
		
		if self.enc_mode == 'binary':
			self.linear = nn.Linear(c_h2 + 2*c_h3, enc_size * enc_size)
		elif self.enc_mode == 'multilabel_binary':
			self.linear = nn.Linear(c_h2 + 2*c_h3, enc_size*2)
		elif self.enc_mode == 'continues' or self.enc_mode == 'one_hot' or self.enc_mode == 'multilabel_binary' or self.enc_mode == 'gumbel_t':
			assert enc_size % 2 == 0
			self.linear = nn.Linear(c_h2 + 2*c_h3, enc_size)
		else:
			raise NotImplementedError('Invalid encoding mode!')

		# normalization layer
		self.ins_norm1 = nn.InstanceNorm1d(c_h2)
		self.ins_norm2 = nn.InstanceNorm1d(c_h2)
		self.ins_norm3 = nn.InstanceNorm1d(c_h2)
		self.ins_norm4 = nn.InstanceNorm1d(c_h2)
		self.ins_norm5 = nn.InstanceNorm1d(c_h2)
		self.ins_norm6 = nn.InstanceNorm1d(c_h2)
		# dropout layer
		self.drop1 = nn.Dropout(p=dp)
		self.drop2 = nn.Dropout(p=dp)
		self.drop3 = nn.Dropout(p=dp)
		self.drop4 = nn.Dropout(p=dp)
		self.drop5 = nn.Dropout(p=dp)
		self.drop6 = nn.Dropout(p=dp)

	def conv_block(self, x, conv_layers, norm_layers, seg_len, res=True):
		out = x
		for layer in conv_layers:
			out = pad_layer(out, layer, self.seg_len)
			out = F.leaky_relu(out, negative_slope=self.ns)
		for layer in norm_layers:
			out = layer(out)
		if res:
			x_pad = F.pad(x, pad=(0, x.size(2) % 2), mode='constant' if seg_len < 64 else 'reflect')
			x_down = F.avg_pool1d(x_pad, kernel_size=2)
			out = x_down + out 
		return out

	def dense_block(self, x, layers, norm_layers, res=True):
		out = x
		for layer in layers:
			out = linear(out, layer)
			out = F.leaky_relu(out, negative_slope=self.ns)
		for layer in norm_layers:
			out = layer(out)
		if res:
			out = out + x
		return out

	def forward(self, x):
		outs = []
		for l in self.conv1s:
			out = pad_layer(x, l, self.seg_len)
			outs.append(out)
		out = torch.cat(outs + [x], dim=1)
		out = F.leaky_relu(out, negative_slope=self.ns)
		out = self.conv_block(out, [self.conv2], [self.ins_norm1, self.drop1], self.seg_len, res=False)
		out = self.conv_block(out, [self.conv3, self.conv4], [self.ins_norm2, self.drop2], self.seg_len)
		out = self.conv_block(out, [self.conv5, self.conv6], [self.ins_norm3, self.drop3], self.seg_len)
		out = self.conv_block(out, [self.conv7, self.conv8], [self.ins_norm4, self.drop4], self.seg_len)
		# dense layer
		out = self.dense_block(out, [self.dense1, self.dense2], [self.ins_norm5, self.drop5], res=True)
		out = self.dense_block(out, [self.dense3, self.dense4], [self.ins_norm6, self.drop6], res=True)
		out_rnn = RNN(out, self.RNN)
		out = torch.cat([out, out_rnn], dim=1)
		
		if self.enc_mode == 'continues':
			out = linear(out, self.linear)
			out_act = F.leaky_relu(out, negative_slope=self.ns)
		
		elif self.enc_mode == 'one_hot':
			out = linear(out, self.linear)
			out_act = gumbel_softmax(out.permute(0, 2, 1))
			out_act = out_act.permute(0, 2, 1).contiguous()
		
		elif self.enc_mode == 'binary':
			out = linear(out, self.linear)
			out_proj = out.permute(0, 2, 1) # shape: (batch_size, t_step, enc_size^2)
			out_proj = out_proj.view(out_proj.size(0), out_proj.size(1), self.enc_size, self.enc_size) # shape: (batch_size, t_step, enc_size, enc_size)
			out_act = gumbel_softmax(out_proj).sum(2).view(out_proj.size(0), out_proj.size(1), -1) # shape: (batch_size, t_step, enc_size)
			out_act = torch.clamp(out_act, min=0, max=1) # binarize output
			out_act = out_act.permute(0, 2, 1).contiguous() # shape: (batch_size, enc_size, t_step)
		
		elif self.enc_mode == 'multilabel_binary':
			out = linear(out, self.linear) # shape: (batch_size, enc_size*2, t_step)
			out_proj = out.permute(0, 2, 1) # shape: (batch_size, t_step, enc_size*2)
			out_proj = out_proj.view(out_proj.size(0), out_proj.size(1), self.enc_size, 2) # shape: (batch_size, t_step, enc_size, 2)
			out_act = gumbel_softmax(out_proj)[:, :, :, 0] # shape: (batch_size, t_step, enc_size, 1)
			out_act = out_act.view(out_act.size(0), out_act.size(1), self.enc_size) # shape: (batch_size, t_step, enc_size)
			out_act = out_act.permute(0, 2, 1).contiguous() # shape: (batch_size, enc_size, t_step)

		elif self.enc_mode == 'gumbel_t':
			out = linear(out, self.linear)
			out_act = gumbel_softmax(out)

		else:
			raise NotImplementedError('Invalid encoding mode!')
		
		return out_act, out


class Enhanced_Generator(nn.Module):
	def __init__(self, ns, dp, enc_size, emb_size, seg_len, n_speakers):
		super(Enhanced_Generator, self).__init__()
		
		self.Encoder = Encoder(ns=ns, dp=dp, enc_size=enc_size, seg_len=seg_len, enc_mode='continues')
		self.Decoder = Decoder(ns=ns, c_in=enc_size, c_h=emb_size, c_a=n_speakers, seg_len=seg_len)

	def forward(self, x, c):
		enc_act, enc = self.Encoder(x)
		x_dec = self.Decoder(enc_act, c)
		return x_dec


class Patcher(nn.Module):
	def __init__(self, c_in=512, c_out=513, c_h=512, c_a=8, ns=0.2, seg_len=64):
		super(Patcher, self).__init__()
		self.ns = ns
		self.seg_len = seg_len
		self.input_layer = nn.Linear(c_in, c_h)
		self.dense1 = nn.Linear(c_h, c_h)
		self.dense2 = nn.Linear(c_h, c_h)
		self.dense3 = nn.Linear(c_h, c_h)
		self.dense4 = nn.Linear(c_h, c_h)
		self.RNN = nn.GRU(input_size=c_h, hidden_size=c_h//2, num_layers=1, bidirectional=True)
		self.dense5 = nn.Linear(2*c_h + c_h, c_h)
		self.linear = nn.Linear(c_h, c_out)
		# normalization layer
		self.ins_norm1 = nn.InstanceNorm1d(c_h)
		self.ins_norm2 = nn.InstanceNorm1d(c_h)
		# embedding layer
		self.emb1 = nn.Embedding(c_a, c_h)
		self.emb2 = nn.Embedding(c_a, c_h)

	def dense_block(self, x, emb, layers, norm_layer, res=True):
		out = x
		for layer in layers:
			out = out + emb.view(emb.size(0), emb.size(1), 1)
			out = linear(out, layer)
			out = F.leaky_relu(out, negative_slope=self.ns)
		out = norm_layer(out)
		if res:
			out = out + x
		return out

	def forward(self, x, c):
		# input layer
		out = linear(x, self.input_emb)
		# dense layer
		out = self.dense_block(out, self.emb1(c), [self.dense1, self.dense2], self.ins_norm1, res=True)
		out = self.dense_block(out, self.emb1(c), [self.dense3, self.dense4], self.ins_norm2, res=True)
		emb = self.emb2(c)
		out_add = out + emb.view(emb.size(0), emb.size(1), 1)
		# rnn layer
		out_rnn = RNN(out_add, self.RNN)
		out = torch.cat([out, out_rnn], dim=1)
		out = append_emb(self.emb2(c), out.size(2), out)
		out = linear(out, self.dense5)
		out = F.leaky_relu(out, negative_slope=self.ns)
		out = linear(out, self.linear)
		out = torch.sigmoid(out)
		return out		